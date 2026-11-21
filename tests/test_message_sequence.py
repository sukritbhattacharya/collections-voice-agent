"""The message list the core sends must be one the API will accept.

Every other test in this suite runs against `StubClient`, which accepts any
sequence of roles at all. That is what let a 400 reach a live call: the
templated opening seeded `user -> assistant -> system`, which reads naturally
and is rejected, and nothing in 121 passing tests could see it because none of
them built a real request.

So the rule is asserted structurally here, mirroring the API's own constraint.
It costs no network call and no key, and it fails on the sequence rather than
on the symptom three layers downstream. See D-041.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.core import outcomes as outcomes_mod
from src.core.agent_core import CollectionsAgent
from src.core.policy import ACCOUNTS
from src.core.stub_client import StubClient


@pytest.fixture(autouse=True)
def _no_side_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes_mod, "OUTCOMES_LOG", tmp_path / "outcomes.jsonl")
    monkeypatch.delenv("OUTCOME_WEBHOOK_URL", raising=False)


def assert_sendable(messages: list[dict]) -> None:
    """The subset of the API's ordering rules the core can violate.

    1. The conversation opens with a user message.
    2. A system message may only follow a user message. (An assistant message
       ending in a server tool result also qualifies; the core never produces
       one, so treating that case as illegal here is deliberate -- it would be
       a new shape worth a new test.)
    3. No message carries empty content.
    """
    assert messages, "no messages to send"
    assert messages[0]["role"] == "user", (
        f"conversation must open with a user message, got {messages[0]['role']!r}"
    )

    for i, msg in enumerate(messages):
        role = msg["role"]
        assert role in {"user", "assistant", "system"}, f"messages.{i}: bad role {role!r}"
        content = msg.get("content")
        assert content != "" and content is not None, f"messages.{i}: empty content"

        if role == "system":
            assert i > 0, "messages.0: a system message cannot open the conversation"
            prev = messages[i - 1]["role"]
            assert prev == "user", (
                f"messages.{i}: role 'system' must follow a 'user' message, "
                f"but follows {prev!r}"
            )


def _agent(script):
    return CollectionsAgent(
        account=ACCOUNTS["MB-4471"],
        version="v3",
        client=StubClient(script),
        model="stub",
    )


def test_opening_seeds_a_sendable_history():
    """The templated opening is the regression that caused a live 400."""
    agent = _agent(["should not be reached"])
    agent.open_call()
    assert_sendable(agent.messages)


def test_sequence_stays_sendable_through_a_reply():
    agent = _agent(["Thanks for confirming. Your minimum due is pending."])
    agent.open_call()
    agent.respond("Yes, speaking.")
    assert_sendable(agent.messages)


def test_sequence_stays_sendable_when_the_tripwire_fires():
    """The tripwire appends its own system message. It must land legally too."""
    agent = _agent(["Let me get you to a colleague."])
    agent.open_call()
    agent.respond("I just lost my job, I have no money")
    assert_sendable(agent.messages)
    assert any(m["role"] == "system" for m in agent.messages[2:]), (
        "expected the tripwire to have appended a system message"
    )


def test_sequence_stays_sendable_in_devanagari():
    """Deepgram returns Devanagari, so this is the live input shape."""
    agent = _agent(["ठीक है।"])
    agent.open_call()
    agent.respond("हां बोलिए.")
    assert_sendable(agent.messages)


def test_validator_rejects_the_shape_that_shipped():
    """Guard the guard: the old ordering must actually fail this check."""
    bad = [
        {"role": "user", "content": "The call has connected."},
        {"role": "assistant", "content": "Hello, this is Priya."},
        {"role": "system", "content": "Account context: ..."},
    ]
    with pytest.raises(AssertionError, match="must follow a 'user' message"):
        assert_sendable(bad)
