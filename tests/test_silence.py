"""What happens when the customer says nothing.

The conversation loop is driven by customer turns. A customer who says nothing
produces no turn, so before this the agent asked its question and waited in
silence until the call ceiling -- four minutes of nothing. Nobody reported it
because nobody sits in silence: every test, scripted or human, answers. See
D-064.
"""

from __future__ import annotations

import pytest

from src.core.agent_core import (
    MAX_SILENCE_PROMPTS,
    SILENCE_SIGN_OFF,
    CollectionsAgent,
)
from src.core.policy import ACCOUNTS
from src.core.stub_client import StubClient


def agent(script: list[str] | None = None) -> CollectionsAgent:
    a = CollectionsAgent(
        account=ACCOUNTS["MB-4471"],
        version="v3",
        client=StubClient(script or ["Am I speaking with Rohan Mehta?"] * 6),
        webhook_url="",
    )
    a.open_call()
    return a


# -- it asks again ---------------------------------------------------------

def test_the_agent_asks_again_on_silence():
    a = agent()
    turn = a.reprompt()
    assert turn is not None
    assert turn.text
    assert a.state.silence_prompts == 1


def test_the_model_is_told_the_silence_is_an_instruction_not_speech():
    """A bracketed note read as customer speech would have the agent replying
    to a stage direction."""
    a = agent()
    a.reprompt()
    last_user = [m for m in a.messages if m["role"] == "user"][-1]
    assert "SYSTEM:" in last_user["content"]
    assert "not something the customer said" in last_user["content"]


def test_the_first_reprompt_repeats_the_question():
    a = agent()
    a.reprompt()
    instruction = [m for m in a.messages if m["role"] == "user"][-1]["content"]
    assert "Ask your last question again" in instruction
    assert "fewer words" in instruction


def test_the_second_reprompt_checks_they_are_there():
    a = agent()
    a.reprompt()
    a.reprompt()
    instruction = [m for m in a.messages if m["role"] == "user"][-1]["content"]
    assert "still there" in instruction


# -- it gives up, and not before -------------------------------------------

def test_it_gives_up_after_the_budget():
    a = agent()
    for _ in range(MAX_SILENCE_PROMPTS):
        assert a.reprompt() is not None
    assert a.reprompt() is None


def test_giving_up_closes_the_call_and_says_so():
    a = agent()
    for _ in range(MAX_SILENCE_PROMPTS):
        a.reprompt()
    assert a.reprompt() is None
    assert a.state.ended_on_silence is True
    assert a.ended is True
    assert a.transcript[-1]["text"] == SILENCE_SIGN_OFF


def test_the_sign_off_is_deterministic_not_generated():
    """It is the last thing the customer may hear. A model asked to improvise
    a goodbye to silence has been observed to summarise a call that did not
    happen -- inventing a commitment nobody made."""
    a = agent(script=["I SHOULD NOT BE SPOKEN"] * 6)
    for _ in range(MAX_SILENCE_PROMPTS + 1):
        a.reprompt()
    assert a.transcript[-1]["text"] == SILENCE_SIGN_OFF


def test_further_calls_stay_closed():
    a = agent()
    for _ in range(MAX_SILENCE_PROMPTS + 3):
        a.reprompt()
    assert a.state.silence_prompts == MAX_SILENCE_PROMPTS


# -- a re-prompt is not a customer turn ------------------------------------

def test_a_reprompt_does_not_count_as_a_customer_turn():
    """Otherwise a silent customer inflates turn_count and eats the
    post-outcome ceiling -- being quiet must not end the call early, nor hold
    it open."""
    a = agent()
    before = len([t for t in a.transcript if t["role"] == "customer"])
    a.reprompt()
    after = len([t for t in a.transcript if t["role"] == "customer"])
    assert before == after == 0


def test_reprompt_turns_are_marked_in_the_transcript():
    """A reviewer reading the transcript needs to know the agent spoke twice
    because nobody answered, not because it repeated itself."""
    a = agent()
    a.reprompt()
    assert a.transcript[-1].get("after_silence") is True


def test_a_normal_turn_is_not_marked():
    a = agent(script=["Thank you for confirming."])
    a.respond("Yes, that's me.")
    assert a.transcript[-1].get("after_silence") is None


# -- the counter survives into the record ----------------------------------

@pytest.mark.asyncio
async def test_the_outcome_records_that_nobody_answered():
    a = agent()
    for _ in range(MAX_SILENCE_PROMPTS + 1):
        a.reprompt()
    outcome = await a.finish()
    # No conversation happened, so there is nothing to capture -- the call
    # must still produce a record, routed to a human to retry.
    assert outcome.outcome.value == "DISPUTE_OR_TRANSFER"
    assert outcome.turn_count == 0


# -- the voice layer is actually wired to it -------------------------------

def test_the_voice_loop_calls_reprompt():
    """The core cannot notice silence by itself. If this wiring is lost the
    core's handling is dead code and nothing fails."""
    import inspect

    from src.voice import agent as voice

    src = inspect.getsource(voice.entrypoint)
    assert "core.reprompt" in src
    assert "SILENCE_SEC" in src
    assert "SILENCE_SIGN_OFF" in src


def test_the_silence_window_is_a_sane_length():
    from src.voice.agent import SILENCE_SEC

    assert 5 <= SILENCE_SEC <= 12, "too short interrupts; too long reads as dead"
