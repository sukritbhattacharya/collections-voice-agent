"""Identifiers are sequences of digits, not quantities.

The live failure: the agent read card `8842` as "eight eight forty-two". Across
every transcript on disk it emitted a raw four-digit card number 126 times and
spelled it out 132 times -- a coin flip, which is what a prompt instruction
buys. The helpline `1800-123-4567` was raw 165 times out of 165, where place
value gives "one thousand eight hundred, one hundred twenty-three, four
thousand five hundred sixty-seven". See D-062.
"""

from __future__ import annotations

import pytest

from src.core.guardrails.speech import verbalise

CARD = "8842"
OTP = "4471"
HELPLINE = "1800-123-4567"
IDS = (CARD, OTP, HELPLINE)


def say(text: str, ids: tuple[str, ...] = IDS) -> str:
    return verbalise(text, ids)[0]


# -- identifiers are spelled out -------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("your card ending in 8842", "eight eight four two"),
    ("the card ending 8842 is overdue", "eight eight four two"),
    ("card 8842", "eight eight four two"),
    # a bare identifier, with no introducing word, is still an identifier
    ("I have 8842 on file", "eight eight four two"),
    ("is the code 4471?", "four four seven one"),
    ("read back 4471 for me", "four four seven one"),
])
def test_known_identifiers_are_spoken_digit_by_digit(text, expected):
    assert expected in say(text)


def test_a_phone_number_keeps_its_groups_as_pauses():
    """The commas are the point -- they give speech a pause, which is what
    makes a long number possible to write down while hearing it."""
    out = say("call the helpline on 1800-123-4567")
    assert "one eight zero zero, one two three, four five six seven" in out


def test_an_unknown_long_number_is_still_treated_as_a_sequence():
    """A number we were not told about, in a phone shape, is not a quantity."""
    assert "nine eight seven" in say("my number is 9876543210", ids=())


def test_a_run_introduced_by_a_lead_word_is_spelled_even_if_unknown():
    assert "five five two nine" in say("the card ending in 5529", ids=())


# -- quantities are left exactly alone -------------------------------------

@pytest.mark.parametrize("text", [
    "a late fee of 750 rupees applies",
    "your minimum due is 4,500 rupees",
    "balances over 10,000 rupees",
    "interest is 3.5 percent a month",
    "that was due on the 9th of November",
    "it takes 2 working days to reflect",
    "the balance is 47,500 rupees",
])
def test_amounts_and_dates_are_untouched(text):
    """Place value is correct for a quantity. Spelling 750 digit by digit
    would be a new error, not a fix."""
    assert say(text) == text


def test_nothing_happens_to_text_with_no_digits():
    line = "I can't approve a waiver, but a colleague will call you back."
    assert say(line) == line


def test_empty_text_is_safe():
    assert verbalise("", IDS) == ("", [])


# -- the audit note --------------------------------------------------------

def test_each_rewrite_is_reported_for_the_transcript():
    _, notes = verbalise("card ending in 8842, helpline 1800-123-4567", IDS)
    assert len(notes) == 2
    assert any("8842" in n for n in notes)


def test_no_note_when_nothing_changed():
    assert verbalise("a late fee of 750 rupees", IDS)[1] == []


def test_running_it_twice_changes_nothing_further():
    once = say("your card ending in 8842")
    assert say(once) == once


# -- the ordering that matters ---------------------------------------------

def test_it_runs_after_the_filter_not_before():
    """The filter matches this account's protected figures as digit strings.
    If digits became words first, an amount would have a way past it. This
    asserts the wiring, since the risk is an ordering mistake rather than a
    logic one."""
    import inspect

    from src.core import agent_core

    src = inspect.getsource(agent_core.CollectionsAgent._generate)
    assert src.index("filter_output(") < src.index("verbalise_identifiers(")


def test_the_agent_knows_which_sequences_are_identifiers():
    from src.core.agent_core import CollectionsAgent
    from src.core.policy import ACCOUNTS, ISSUER_HELPLINE
    from src.core.stub_client import StubClient

    acc = ACCOUNTS["MB-4471"]
    a = CollectionsAgent(
        account=acc, version="v3", client=StubClient(["ok"]), webhook_url="",
    )
    assert acc.card_last4 in a.spoken_ids
    assert acc.otp in a.spoken_ids
    assert ISSUER_HELPLINE in a.spoken_ids
    # amounts must NOT be here: place value is right for them
    assert str(int(acc.minimum_due_inr)) not in a.spoken_ids
    assert str(int(acc.outstanding_inr)) not in a.spoken_ids


# -- full stops the model puts between digits ------------------------------

@pytest.mark.parametrize("text,expected", [
    ("The card ending in five. five. two. nine. The payment is due.",
     "The card ending in five five two nine. The payment is due."),
    ("Read back four. four. seven. one.", "Read back four four seven one."),
    ("one. eight. zero. zero.", "one eight zero zero."),
])
def test_stops_between_digit_words_are_collapsed(text, expected):
    """The model wrote "five. five. two. nine." unprompted. Speech gives a
    full stop a sentence-length pause, so the card number is read out with
    gaps that sound like hesitation."""
    assert say(text) == expected


@pytest.mark.parametrize("text", [
    "That was due. The fee applies.",
    "a late fee of 750 rupees. Clearing it helps.",
    "Thank you. Have a good day.",
    "Nine. Then we are done.",
])
def test_real_sentence_boundaries_survive(text):
    """Only a stop between two digit words is collapsed. "Nine. Then" is a
    sentence ending, not a digit sequence."""
    assert say(text) == text


def test_the_collapse_is_recorded():
    _, notes = verbalise("ending in five. five. two. nine.", ("5529",))
    assert any("full stops" in n for n in notes)
