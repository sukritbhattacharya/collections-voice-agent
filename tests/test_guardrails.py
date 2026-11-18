"""Every guardrail rule has a test that proves it fires, and a test that proves
it stays quiet on legitimate output.

The negative cases matter as much as the positive ones. A filter that blocks
correct utterances inflates the violation count we report and degrades the call
-- it replaces good output with different, blander output. Both directions are
defects.
"""

from __future__ import annotations

import pytest

from src.core.guardrails import input_tripwire
from src.core.guardrails.output_filter import check

# --------------------------------------------------------------------------
# Output filter -- things the agent must never say
# --------------------------------------------------------------------------

BLOCKED = [
    # credit_bureau
    ("credit_bureau", "This will damage your CIBIL score badly."),
    ("credit_bureau", "Non-payment affects your credit rating."),
    ("credit_bureau", "Your score will drop if you do not pay."),
    ("credit_bureau", "It gets reported to Experian and Equifax."),
    ("credit_bureau", "This will affect your loan eligibility in future."),
    # legal_threat
    ("legal_threat", "We may initiate legal action against you."),
    ("legal_threat", "The bank can take you to court for this."),
    ("legal_threat", "Our lawyer will contact you next week."),
    ("legal_threat", "We will file a police complaint against you."),
    ("legal_threat", "A recovery agent will visit your home."),
    # waiver_or_discount_approval
    ("waiver_or_discount_approval", "I can waive the late fee for you today."),
    ("waiver_or_discount_approval", "Your waiver is approved."),
    ("waiver_or_discount_approval", "I will give you 50 percent off."),
    ("waiver_or_discount_approval", "We can offer a one time settlement."),
    ("waiver_or_discount_approval", "I can remove the late fee."),
    # cross_sell
    ("cross_sell", "You are eligible for our festive loan at 9.5 percent."),
    ("cross_sell", "Would you like to open a fixed deposit with us?"),
    ("cross_sell", "We have a pre-approved personal loan for you."),
    ("cross_sell", "Can I interest you in our insurance policy cover?"),
    # wrong_interest_rate
    ("wrong_interest_rate", "The interest rate is around 12 percent."),
    ("wrong_interest_rate", "Interest is charged at two percent per month."),
    # wrong_late_fee
    ("wrong_late_fee", "The late fee is 1500 rupees."),
    ("wrong_late_fee", "A late payment fee of fifteen hundred rupees applies."),
    # hindi_output
    ("hindi_output", "आपका भुगतान बकाया है।"),
]

ALLOWED = [
    "The interest on your card is three point five percent per month.",
    "The interest rate is 3.5 percent per month.",
    "A late fee of seven hundred and fifty rupees applies.",
    "The late fee is 750 rupees if the outstanding is over 10,000 rupees.",
    "I cannot approve a waiver, but I will note your request.",
    "I am not able to approve any waiver myself.",
    "I am only here for your pending payment.",
    "When can you make the payment on your card?",
    "Your payment will reflect in two working days.",
    "Thank you, I have noted that you paid by NEFT on Monday.",
    "Let me connect you to a colleague who can help with that.",
    "Your late fee query is noted, a colleague will call you in 2 days.",
]


@pytest.mark.parametrize("rule_id,text", BLOCKED, ids=[f"{r}:{t[:28]}" for r, t in BLOCKED])
def test_forbidden_output_is_blocked(rule_id: str, text: str) -> None:
    result = check(text)
    assert result.blocked, f"{rule_id} did not fire on: {text}"
    assert result.violations[0].rule_id == rule_id, (
        f"expected {rule_id}, got {result.violations[0].rule_id} on: {text}"
    )
    assert result.text != text, "blocked utterance must be replaced"


@pytest.mark.parametrize("text", ALLOWED, ids=[t[:34] for t in ALLOWED])
def test_legitimate_output_passes(text: str) -> None:
    result = check(text)
    assert not result.blocked, (
        f"false positive {[str(v) for v in result.violations]} on: {text}"
    )
    assert result.text == text


def test_every_output_rule_has_a_test() -> None:
    """A rule nobody tests is a rule nobody can trust."""
    from src.core.guardrails.output_filter import _rules

    defined = {r["id"] for r in _rules()}
    covered = {rule_id for rule_id, _ in BLOCKED} | {"balance_before_verification"}
    assert defined == covered, f"untested rules: {defined - covered}"


# --------------------------------------------------------------------------
# Balance disclosure -- gated on verification, so it needs its own cases
# --------------------------------------------------------------------------

PROTECTED = ["47500", "47,500", "4500", "4,500"]


@pytest.mark.parametrize(
    "text",
    [
        "Your outstanding balance is 47,500 rupees.",
        "The minimum due is 4500 rupees.",
        "You owe forty seven thousand five hundred rupees.",
    ],
)
def test_amounts_blocked_before_verification(text: str) -> None:
    result = check(text, protected_values=PROTECTED, otp_verified=False)
    assert result.blocked
    assert result.violations[0].rule_id == "balance_before_verification"


@pytest.mark.parametrize(
    "text",
    [
        "Your outstanding balance is 47,500 rupees.",
        "The minimum due is 4500 rupees.",
    ],
)
def test_amounts_allowed_after_verification(text: str) -> None:
    result = check(text, protected_values=PROTECTED, otp_verified=True)
    assert not result.blocked
    assert result.text == text


def test_unrelated_numbers_not_mistaken_for_balance() -> None:
    result = check(
        "I will call you back on the 24th at 4 pm.",
        protected_values=PROTECTED,
        otp_verified=False,
    )
    assert not result.blocked


# --------------------------------------------------------------------------
# Input tripwire -- what must force a hand-over
# --------------------------------------------------------------------------

TRIGGERS = [
    ("ABUSE", "You people are bloody idiots, stop calling me."),
    ("ABUSE", "Shut up and get lost."),
    ("ABUSE", "Abe chutiya, phone mat karo."),
    ("MEDICAL_EMERGENCY", "My father is in the ICU, I cannot deal with this."),
    ("MEDICAL_EMERGENCY", "I had an accident last week and I am in hospital."),
    ("MEDICAL_EMERGENCY", "Meri wife bahut bimaar hai."),
    ("MEDICAL_EMERGENCY", "My mother passed away last month."),
    ("JOB_LOSS", "I lost my job two months ago."),
    ("JOB_LOSS", "I was laid off in the restructuring."),
    ("JOB_LOSS", "Meri naukri chali gayi hai."),
    ("JOB_LOSS", "The company shut down and I am unemployed."),
]


@pytest.mark.parametrize("reason,text", TRIGGERS, ids=[f"{r}:{t[:26]}" for r, t in TRIGGERS])
def test_tripwire_fires(reason: str, text: str) -> None:
    hit = input_tripwire.scan(text)
    assert hit is not None, f"no trigger on: {text}"
    assert hit.reason == reason, f"expected {reason}, got {hit.reason} on: {text}"


NO_TRIGGER = [
    "I will pay on Friday.",
    "I already paid through NEFT yesterday.",
    "Can you waive the late fee?",
    "I do not have money right now, salary is delayed.",
    "This is not a good time, call me tomorrow.",
    "What is the interest rate on this card?",
    "Mujhe thoda time chahiye, agle hafte kar dunga.",
]


@pytest.mark.parametrize("text", NO_TRIGGER, ids=[t[:30] for t in NO_TRIGGER])
def test_ordinary_collections_talk_does_not_trigger(text: str) -> None:
    """Financial hardship is the normal subject of these calls.

    "I have no money" is not a job loss and must not transfer, or every call
    ends with a human and the agent is pointless.
    """
    assert input_tripwire.scan(text) is None, (
        f"false transfer on: {text} -> {input_tripwire.scan(text)}"
    )


def test_abuse_takes_priority_over_other_triggers() -> None:
    """An abusive customer who also mentions job loss goes to the abuse queue."""
    hit = input_tripwire.scan("I lost my job you bloody idiots!")
    assert hit is not None and hit.reason == "ABUSE"
