"""Speech-recognition repairs, and the limits on them.

The live failure: a customer says "ji" (yes) and Nova-3 returns the letter
"G". The agent answered "Sorry, I didn't catch that clearly" -- on identity
confirmation, which stalls the whole call. See D-051.
"""

from __future__ import annotations

import pytest

from src.core.agent_core import CollectionsAgent
from src.core.guardrails.transcription import repair
from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID
from src.core.stub_client import StubClient


def agent() -> CollectionsAgent:
    a = CollectionsAgent(
        ACCOUNTS[DEFAULT_CUSTOMER_ID],
        version="v3",
        client=StubClient(["Thank you for confirming, Rohan."]),
    )
    a.open_call()
    return a


# -- the repair table -------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("G", "Ji"),
        ("g", "Ji"),
        ("G.", "Ji"),
        ("G?", "Ji"),
        ("  G  ", "Ji"),
        ("gee", "Ji"),
        ("jee", "Ji"),
        ("G haan", "Ji haan"),
        ("haan G", "Haan ji"),
        ("G nahi", "Ji nahi"),
        ("nahi G", "Nahi ji"),
    ],
)
def test_recognition_artefacts_are_repaired(raw: str, expected: str) -> None:
    repaired, note = repair(raw)
    assert repaired == expected
    assert note, "a repair must leave an audit note"


@pytest.mark.parametrize(
    "text",
    [
        "Ji",
        "Haan",
        "Nahi",
        "Yes",
        # Already-correct Hinglish is left alone: the model reads it fine.
        "Ji haan, Rohan bol raha hoon",
        # A letter inside a sentence is not touched -- context already
        # carries the meaning, and a customer may have spelled something.
        "G, Rohan bol raha hoon",
        "Main G block mein rehta hoon",
        "",
    ],
)
def test_everything_else_is_left_exactly_as_heard(text: str) -> None:
    repaired, note = repair(text)
    assert repaired == text
    assert note is None


def test_repair_is_idempotent() -> None:
    """Running it twice must not keep rewriting."""
    once, _ = repair("G")
    twice, note = repair(once)
    assert twice == once
    assert note is None


# -- what the agent does with it --------------------------------------------

def test_the_model_reads_the_repair() -> None:
    a = agent()
    a.respond("G")
    user_turns = [m for m in a.messages if m["role"] == "user"]
    assert user_turns[-1]["content"] == "Ji"


def test_the_transcript_keeps_what_recognition_actually_produced() -> None:
    """The record must not report better input than arrived."""
    a = agent()
    a.respond("G")
    entry = next(e for e in a.transcript if e["role"] == "customer")
    assert entry["text"] == "G"
    assert entry["repaired_to"] == "Ji"


def test_repairs_are_recorded_for_audit() -> None:
    a = agent()
    a.respond("G")
    assert a.state.transcription_repairs == ["'G' -> 'Ji'"]


def test_repairs_do_not_pollute_the_compliance_gates() -> None:
    """A misheard syllable is an input-quality event, not a breach.

    Counting it in guardrail_hits would make G1-G4 report violations that
    never happened.
    """
    a = agent()
    a.respond("G")
    assert a.state.guardrail_hits == []


def test_an_untouched_turn_records_nothing() -> None:
    a = agent()
    a.respond("Ji haan")
    assert a.state.transcription_repairs == []
    entry = next(e for e in a.transcript if e["role"] == "customer")
    assert "repaired_to" not in entry
