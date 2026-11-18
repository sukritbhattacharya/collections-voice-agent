"""End-to-end tests of the conversation loop, using a scripted stand-in model.

These prove the loop itself works -- tools dispatch, guardrails fire inside the
real path rather than only in isolation, outcomes get captured, and the version
flags actually change behaviour. No network, no API key, no cost.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from src.core import outcomes as outcomes_mod
from src.core.agent_core import CollectionsAgent
from src.core.outcomes import OutcomeType, TransferReason
from src.core.policy import ACCOUNTS
from src.core.stub_client import StubClient

FRIDAY = (date.today() + timedelta(days=3)).isoformat()


@pytest.fixture(autouse=True)
def _no_side_effects(tmp_path, monkeypatch):
    """Keep test outcomes out of results/ and off the network."""
    monkeypatch.setattr(outcomes_mod, "OUTCOMES_LOG", tmp_path / "outcomes.jsonl")
    monkeypatch.delenv("OUTCOME_WEBHOOK_URL", raising=False)


def _agent(script, version="v3"):
    return CollectionsAgent(
        account=ACCOUNTS["MB-4471"],
        version=version,
        client=StubClient(script),
        model="stub",
    )


def test_happy_path_captures_promise_to_pay():
    agent = _agent([
        ("get_account_context", {}),
        "Good morning, this is Mumbai Bank calling about your credit card. "
        "Am I speaking with Rohan Mehta?",
        "Thank you. Your minimum payment is overdue. When can you clear it?",
        ("log_outcome", {
            "outcome": "PROMISE_TO_PAY", "ptp_date": FRIDAY,
            "ptp_amount_inr": 4500, "payment_mode": None, "paid_on": None,
            "callback_at": None, "transfer_reason": None,
            "summary": "Will pay Friday",
        }),
        "Thank you, I have noted that. Goodbye.",
    ])

    opening = agent.open_call()
    assert "Rohan Mehta" in opening.text
    assert [e.name for e in opening.tool_events] == ["get_account_context"]

    agent.respond("Yes, speaking.")
    agent.respond("I can pay on Friday.")

    outcome = asyncio.run(agent.finish())
    assert outcome.outcome is OutcomeType.PROMISE_TO_PAY
    assert outcome.ptp_amount_inr == 4500
    assert outcome.captured_by == "agent"
    assert outcome.turn_count == 2


def test_output_filter_blocks_forbidden_speech_inside_the_loop():
    """A unit test proves the rule matches. This proves it is wired in."""
    agent = _agent([
        "If you do not pay, this will badly damage your CIBIL score.",
    ])
    turn = agent.open_call()

    assert turn.violations == ["compliance:credit_bureau"]
    assert "CIBIL" not in turn.text
    assert "pending payment" in turn.text
    assert agent.transcript[-1]["text"] == turn.text, (
        "the transcript must record what was actually said"
    )


def test_v2_has_no_output_filter():
    """Isolates the guardrail layer: same prompt, same tools, filter off."""
    agent = _agent(
        ["If you do not pay, this will damage your CIBIL score."], version="v2"
    )
    turn = agent.open_call()
    assert turn.violations == []
    assert "CIBIL" in turn.text


def test_abuse_forces_transfer_regardless_of_the_model():
    """The model is scripted to keep pitching. The tripwire overrules it."""
    agent = _agent([
        "Good morning, this is Mumbai Bank.",
        "So when can you make the payment?",  # model ignores the abuse
    ])
    agent.open_call()
    turn = agent.respond("You people are bloody idiots, stop calling me.")

    assert turn.forced_transfer == "ABUSE"
    assert agent.state.transfer_requested is True
    assert "tripwire:abuse" in agent.state.guardrail_hits
    operator = [m for m in agent.messages if m["role"] == "system"]
    assert operator and "ABUSE" in operator[0]["content"]


def test_hardship_without_job_loss_does_not_transfer():
    """Being short of money is the normal subject of these calls."""
    agent = _agent(["Good morning.", "I understand. When could you manage it?"])
    agent.open_call()
    turn = agent.respond("I don't have money right now, salary is delayed.")
    assert turn.forced_transfer is None
    assert agent.state.transfer_requested is False


def test_balance_withheld_until_verified_then_released():
    agent = _agent([
        "Your outstanding balance is 47,500 rupees.",       # before OTP
        ("verify_otp", {"code": "4471"}),
        "Thank you. Your outstanding balance is 47,500 rupees.",  # after OTP
    ])
    blocked = agent.open_call()
    assert blocked.violations == ["compliance:balance_before_verification"]
    assert "47,500" not in blocked.text

    allowed = agent.respond("My code is 4471.")
    assert allowed.violations == []
    assert "47,500" in allowed.text


def test_v1_cannot_reach_the_fact_tools():
    """v1 is the original prompt with outcome logging only."""
    agent = _agent([("get_account_context", {})], version="v1")
    turn = agent.open_call()
    assert turn.tool_events == []
    assert "not available" in turn.text


def test_missing_outcome_falls_back_rather_than_failing():
    """A call that logs nothing must still produce a record."""
    agent = _agent(["Hello?", "Are you there?"], version="v2")  # extractor off
    agent.open_call()
    agent.respond("...")

    outcome = asyncio.run(agent.finish())
    assert outcome.outcome is OutcomeType.DISPUTE_OR_TRANSFER
    assert outcome.transfer_reason is TransferReason.OTHER
    assert outcome.captured_by == "fallback"


def test_invalid_outcome_is_returned_to_the_model_for_repair():
    agent = _agent([
        ("log_outcome", {
            "outcome": "PROMISE_TO_PAY", "ptp_date": None,
            "ptp_amount_inr": None, "payment_mode": None, "paid_on": None,
            "callback_at": None, "transfer_reason": None, "summary": "vague",
        }),
        ("log_outcome", {
            "outcome": "PROMISE_TO_PAY", "ptp_date": FRIDAY,
            "ptp_amount_inr": 4500, "payment_mode": None, "paid_on": None,
            "callback_at": None, "transfer_reason": None, "summary": "fixed",
        }),
        "Noted, thank you.",
    ])
    agent.open_call()

    first, second = agent.registry.events[0], agent.registry.events[1]
    assert first.result["logged"] is False
    assert "requires" in first.result["error"]
    assert second.result["logged"] is True
