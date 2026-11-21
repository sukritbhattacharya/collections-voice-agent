"""Waiving a fee that was never charged.

The live failure, on `MB-9023` (balance 8,200 -- below the 10,000 threshold,
so no late fee is due): the customer asked four times to have the late fee
waived, and the agent noted the request, declined to approve it, and promised a
colleague would call back. Every compliance rule held. No figure was misstated,
so nothing fired. But the customer rang off believing she owed a fee she did
not, and a human was committed to calling her back about nothing.

The disclosure rule added in D-054 is what put the agent in that position: it
may not say a fee is due, and it may not say none is due either, because
either answer reveals which side of the threshold the balance sits on. What it
was never told is what to do when the *customer* asserts the fee. Agreeing was
the model's default. See D-058.
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from src.core.policy import ACCOUNTS, CallState, compute_late_fee
from src.core.tools import ToolRegistry


FEE_ACCOUNT = "MB-4471"      # 47,500 outstanding -- fee applies
NO_FEE_ACCOUNT = "MB-9023"   # 8,200 outstanding  -- no fee
BOUNDARY_ACCOUNT = "MB-5567" # 10,001 outstanding -- fee applies, by one rupee


def runner(customer_id: str, *, verified: bool = False) -> ToolRegistry:
    state = CallState(account=ACCOUNTS[customer_id])
    if verified:
        state.verify_otp(ACCOUNTS[customer_id].otp)
        assert state.otp_verified
    return ToolRegistry(state=state)


def note(customer_id: str, *, verified: bool = False) -> dict:
    return runner(customer_id, verified=verified)._tool_note_waiver_request(
        "waive the late fee"
    )


# -- the tool reports what is actually owed ---------------------------------

def test_fee_account_reports_the_fee_applies():
    assert note(FEE_ACCOUNT)["late_fee_applies"] is True


def test_no_fee_account_reports_no_fee():
    assert note(NO_FEE_ACCOUNT)["late_fee_applies"] is False


def test_one_rupee_over_the_threshold_still_applies():
    """The boundary is where an off-by-one would be invisible and wrong."""
    assert ACCOUNTS[BOUNDARY_ACCOUNT].outstanding_inr == Decimal("10001")
    assert note(BOUNDARY_ACCOUNT)["late_fee_applies"] is True


def test_the_tool_recomputes_rather_than_trusting_the_model():
    """The flag comes from the balance, not from anything the model said."""
    acc = ACCOUNTS[NO_FEE_ACCOUNT]
    assert compute_late_fee(acc.outstanding_inr) == Decimal("0")
    assert note(NO_FEE_ACCOUNT)["late_fee_applies"] is False


# -- nothing is ever approved ----------------------------------------------

def test_no_waiver_is_ever_approved():
    for cid in (FEE_ACCOUNT, NO_FEE_ACCOUNT, BOUNDARY_ACCOUNT):
        for verified in (False, True):
            assert note(cid, verified=verified)["approved"] is False


def test_the_request_is_always_recorded_even_when_there_is_no_fee():
    """The ask happened. An audit trail that drops it is worse than a wasted
    callback -- the customer did request something."""
    r = runner(NO_FEE_ACCOUNT)
    r._tool_note_waiver_request("waive the late fee")
    assert r.state.waiver_requested is True


# -- the instruction differs by what is owed and who is verified -----------

def test_fee_account_gets_the_callback_instruction():
    text = note(FEE_ACCOUNT)["instruction"].lower()
    assert "colleague will call back" in text
    assert "do not approve" in text


def test_unverified_no_fee_refuses_to_engage_without_disclosing():
    text = note(NO_FEE_ACCOUNT)["instruction"].lower()
    # must not let the agent assert the absence yet ...
    assert "do not say" in text or "do not say so yet" in text
    # ... must not let it accept the premise either ...
    assert "do not accept that a fee exists" in text
    # ... and must route to verification rather than silence.
    assert "one-time password" in text


def test_unverified_no_fee_does_not_promise_a_callback():
    """The specific thing that happened on the live call."""
    assert "promise a callback" in note(NO_FEE_ACCOUNT)["instruction"].lower()


def test_verified_no_fee_corrects_the_customer_plainly():
    text = note(NO_FEE_ACCOUNT, verified=True)["instruction"].lower()
    assert "no late fee has been charged" in text
    assert "nothing to waive" in text


def test_verified_no_fee_returns_to_the_payment():
    """Correcting the premise must not lose the call's purpose."""
    assert "minimum payment" in note(NO_FEE_ACCOUNT, verified=True)["instruction"]


# -- a reviewer can see there was nothing to decide ------------------------

def test_a_waiver_on_a_nonexistent_fee_is_flagged_for_the_reviewer():
    r = runner(NO_FEE_ACCOUNT)
    r._tool_note_waiver_request("waive the late fee")
    assert r.state.waiver_on_nonexistent_fee is True


def test_a_real_waiver_request_is_not_flagged():
    r = runner(FEE_ACCOUNT)
    r._tool_note_waiver_request("waive the late fee")
    assert r.state.waiver_on_nonexistent_fee is False


def test_the_flag_is_false_when_no_waiver_was_asked_for():
    assert runner(NO_FEE_ACCOUNT).state.waiver_on_nonexistent_fee is False


def test_the_flag_reaches_the_outcome_payload():
    """`waiver_requested: true` on its own sends a human to call about
    nothing. The distinction has to survive into what the CRM receives."""
    from src.core.outcomes import CallOutcome

    assert "waiver_on_nonexistent_fee" in CallOutcome.model_fields
    assert CallOutcome.model_fields["waiver_on_nonexistent_fee"].default is False


# -- the deterministic backstop --------------------------------------------
#
# The prompt change stopped the agent accepting the premise mid-call, which is
# the larger half of the fix. It did not stop it reintroducing the callback in
# its closing summary: on the replay of the live call the agent held the line
# four times and then signed off with "a colleague will call you back about
# it". A prompt tells the model what to do while it is paying attention. The
# filter does not depend on attention.

from src.core.guardrails.output_filter import check, scan_all

# The filter is gated on the account fact, not on the tool having run --
# see the rule's own note on why.
NO_FEE_FLAGS = {"late_fee_not_owed": True}
FEE_FLAGS = {"late_fee_not_owed": False}

CALLBACK_LINES = [
    "Your waiver request has been noted, and a colleague will call you back about it.",
    "I've noted it and someone will get in touch about the late fee.",
    "A representative will reach out regarding the fee waiver.",
    "I can't decide it myself, but my team will call you back about the charge.",
    # The four below are verbatim from replays of the live call. Every one of
    # them got past the first draft of the rule.
    "I've noted your request, and a colleague will look at it.",
    "I've already noted your request, and a colleague will review it.",
    "So you'll pay on Monday, and the waiver request has been noted for a colleague.",
    "Your request is logged and my team will consider it.",
]


@pytest.mark.parametrize("line", CALLBACK_LINES, ids=lambda s: s[:34])
def test_callback_promise_is_blocked_when_no_fee_is_owed(line):
    result = check(line, call_flags=NO_FEE_FLAGS)
    assert result.blocked, f"not blocked: {line}"
    assert "verified" in result.text.lower()


@pytest.mark.parametrize("line", CALLBACK_LINES, ids=lambda s: s[:34])
def test_the_same_line_is_fine_when_the_fee_is_real(line):
    """The whole point of the flag. On an account that does carry the fee,
    promising a callback is the correct thing to say -- a pattern-only rule
    would have broken the legitimate waiver path."""
    assert not check(line, call_flags=FEE_FLAGS).blocked
    assert not check(line).blocked  # no flags passed at all


def test_the_rule_stands_down_once_the_customer_is_verified():
    """Verified, the agent has been told to say plainly that nothing is
    charged. A callback line after that is untidy, not misleading, and
    blocking it would replace a correct sentence with a verification prompt
    for someone already verified."""
    line = CALLBACK_LINES[0]
    assert not check(line, call_flags=NO_FEE_FLAGS, otp_verified=True).blocked


def test_scoring_can_see_the_rule_too():
    """`scan_all` feeds the scorer. A rule it skips is a rule the eval table
    silently reports as clean."""
    line = CALLBACK_LINES[0]
    ids = {v.rule_id for v in scan_all(line, call_flags=NO_FEE_FLAGS)}
    assert "callback_for_unowed_fee" in ids
    assert not scan_all(line, call_flags=FEE_FLAGS)


def test_the_filter_does_not_wait_for_the_tool_to_have_run():
    """The ordering hole that a replay walked straight through.

    The model said "I will note your request and a colleague will call you
    back" and only then called `note_waiver_request`. Gated on the tool's
    flag, the filter saw `False` and let it through. Gated on the balance, it
    does not -- which is the difference between a control and a convention.
    """
    line = "I will note your request and a colleague will call you back about it."
    # what the first draft had available at that moment: nothing set yet
    assert not check(line, call_flags={"waiver_on_nonexistent_fee": False}).blocked
    # what it has now, from the account, before any tool runs
    assert check(line, call_flags={"late_fee_not_owed": True}).blocked


def test_the_account_fact_is_computed_not_reported():
    from src.core.agent_core import CollectionsAgent
    from src.core.stub_client import StubClient

    for cid, expected in ((NO_FEE_ACCOUNT, True), (FEE_ACCOUNT, False),
                          (BOUNDARY_ACCOUNT, False)):
        a = CollectionsAgent(
            account=ACCOUNTS[cid], version="v3",
            client=StubClient(["ok"]), webhook_url="",
        )
        assert a.no_late_fee is expected, cid


# -- the send step, which had no tool --------------------------------------

def test_an_empty_code_does_not_consume_an_attempt():
    """The live defect: the agent called verify_otp at the moment the customer
    said "yes, send it", before any code existed. That burned one of three
    attempts and forced an apology mid-call."""
    r = runner(FEE_ACCOUNT)
    before = r.state.otp_attempts
    out = r._tool_verify_otp("")
    assert out["verified"] is False
    assert r.state.otp_attempts == before


@pytest.mark.parametrize("code", ["", "   ", "the code they will read back"])
def test_codeless_calls_never_cost_an_attempt(code):
    r = runner(FEE_ACCOUNT)
    r._tool_verify_otp(code)
    assert r.state.otp_attempts == 0


def test_a_real_wrong_code_still_costs_an_attempt():
    """The protection must not become a way to brute-force for free."""
    r = runner(FEE_ACCOUNT)
    r._tool_verify_otp("1234")
    assert r.state.otp_attempts == 1
    assert r.state.otp_verified is False


def test_the_right_code_verifies():
    r = runner(FEE_ACCOUNT)
    assert r._tool_verify_otp(ACCOUNTS[FEE_ACCOUNT].otp)["verified"] is True


def test_a_spoken_code_with_spaces_or_dashes_is_read_as_digits():
    """Speech recognition does not hand back a clean four-digit string."""
    r = runner(FEE_ACCOUNT)
    spaced = " ".join(ACCOUNTS[FEE_ACCOUNT].otp)
    assert r._tool_verify_otp(spaced)["verified"] is True


def test_there_is_a_tool_for_sending_the_code():
    from src.core.tools import TOOL_DEFINITIONS

    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "send_otp" in names, (
        "without this the model reaches for verify_otp at the send step"
    )


def test_sending_marks_the_call_as_waiting_for_a_code():
    r = runner(FEE_ACCOUNT)
    out = r._tool_send_otp()
    assert out["sent"] is True
    assert r.state.otp_sent is True
    assert "read it back" in out["instruction"]


def test_sending_does_not_verify_anybody():
    r = runner(FEE_ACCOUNT)
    r._tool_send_otp()
    assert r.state.otp_verified is False
    assert r.state.otp_attempts == 0


def test_a_code_offered_before_the_send_is_still_checked():
    """The deadlock: the customer read out the correct code before the agent
    had sent one, the agent refused it on ordering grounds, and the call ran
    twenty turns waiting for an SMS. Verification must not depend on the order
    things happened in."""
    r = runner("MB-2214")
    assert r.state.otp_sent is False
    assert r._tool_verify_otp("2214")["verified"] is True


def test_a_second_send_is_refused_and_redirected():
    """The agent sent three codes in one call while being told none arrived."""
    r = runner(FEE_ACCOUNT)
    assert r._tool_send_otp()["sent"] is True
    again = r._tool_send_otp()
    assert again["sent"] is False
    assert again["already_sent"] is True
    assert "callback" in again["instruction"]


# -- verification is reactive, and the prompt says why ---------------------

def test_the_prompt_forbids_offering_verification_unprompted():
    """An outbound caller asking for a code is the shape of a vishing call.
    Reverted from D-059's proactive offer; see D-061."""
    from src.core.agent_core import CollectionsAgent
    from src.core.stub_client import StubClient

    a = CollectionsAgent(
        account=ACCOUNTS[FEE_ACCOUNT], version="v3",
        client=StubClient(["ok"]), webhook_url="",
    )
    prompt = a._build_system_prompt()
    assert "Never raise verification unprompted" in prompt
    assert "only when the customer asks about something on their" in prompt


def test_the_published_terms_reach_the_prompt_as_values_not_prose():
    """The fee rule is how a customer learns a fee exists without verifying.
    The figures must come from the same constants the filter checks against,
    or the prompt can teach the agent a number the filter then blocks."""
    import re

    from src.core.agent_core import CollectionsAgent
    from src.core.policy import (
        INTEREST_PCT_MONTHLY,
        LATE_FEE_INR,
        LATE_FEE_THRESHOLD_INR,
    )
    from src.core.stub_client import StubClient

    a = CollectionsAgent(
        account=ACCOUNTS[FEE_ACCOUNT], version="v3",
        client=StubClient(["ok"]), webhook_url="",
    )
    prompt = a._build_system_prompt()
    assert not re.findall(r"\{[a-z_]+\}", prompt), "unsubstituted placeholder"
    assert f"{INTEREST_PCT_MONTHLY}% a month" in prompt
    assert f"{int(LATE_FEE_INR)} rupees" in prompt
    assert f"{int(LATE_FEE_THRESHOLD_INR):,} rupees" in prompt


def test_the_unverified_tool_instruction_matches_the_prompt():
    """Two places tell the model what it may say before verification. They
    disagreeing is how the agent ends up confidently wrong."""
    from src.core.policy import account_context

    rule = account_context(runner(FEE_ACCOUNT).state)["disclosure_rule"]
    assert "Do NOT offer verification unprompted" in rule
    assert "late fee rule" in rule
