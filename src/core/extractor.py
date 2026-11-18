"""Post-call outcome extraction.

The safety net behind "every call ends with a structured outcome". When the
model fails to call `log_outcome` -- the customer hung up, the turn budget ran
out, it simply did not -- the outcome is read back out of the transcript here.

Deliberately a separate, cheap model call after the call has ended. It is off
the latency path, so correctness matters and speed does not.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .outcomes import CallOutcome, OutcomeType, TransferReason

_INSTRUCTIONS = """\
You are reading the transcript of a completed collections call and recording \
what happened. Report only what the transcript supports.

Choose one outcome:
- PROMISE_TO_PAY: the customer committed to paying. Needs a date and amount.
- ALREADY_PAID: the customer says they have already paid. Needs mode and date.
- CALLBACK_REQUEST: the customer asked to be contacted later. Needs a time.
- DISPUTE_OR_TRANSFER: the call was handed to a human, the customer disputed \
the amount, was abusive, or disclosed a medical emergency or job loss. Needs a \
reason. Use this when nothing was agreed.

If a required detail was never stated, leave it null and pick the outcome that \
fits what is actually there. Do not infer a date the customer did not give. \
Today is {today}.\
"""


class ExtractedOutcome(BaseModel):
    outcome: Literal[
        "PROMISE_TO_PAY", "ALREADY_PAID", "CALLBACK_REQUEST", "DISPUTE_OR_TRANSFER"
    ]
    ptp_date: str | None = Field(None, description="YYYY-MM-DD")
    ptp_amount_inr: int | None = None
    payment_mode: str | None = None
    paid_on: str | None = Field(None, description="YYYY-MM-DD")
    callback_at: str | None = Field(None, description="ISO 8601")
    transfer_reason: Literal[
        "ABUSE", "MEDICAL_EMERGENCY", "JOB_LOSS", "DISPUTE",
        "WAIVER_REQUEST", "WRONG_PERSON", "OTHER",
    ] | None = None
    summary: str


def _render(transcript: list[dict[str, str]]) -> str:
    return "\n".join(f"{t['role'].upper()}: {t['text']}" for t in transcript)


def extract_outcome(
    *,
    transcript: list[dict[str, str]],
    customer_id: str,
    model: str = "claude-haiku-5-5",
) -> CallOutcome | None:
    """Read an outcome out of a finished transcript, or return None."""
    if not transcript:
        return None

    from anthropic import Anthropic

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        system=_INSTRUCTIONS.format(today=date.today().isoformat()),
        messages=[{"role": "user", "content": _render(transcript)}],
        output_config={"format": ExtractedOutcome},
    )
    parsed = response.parsed_output
    if parsed is None:
        return None

    return _to_outcome(parsed, customer_id)


def _to_outcome(parsed: ExtractedOutcome, customer_id: str) -> CallOutcome | None:
    """Build a validated outcome, degrading rather than raising.

    The extractor is the fallback. If what it produced will not validate -- a
    promise with no date, say -- the call still needs a record, so it becomes a
    transfer with a note instead of an exception.
    """
    def _d(value: str | None) -> date | None:
        try:
            return date.fromisoformat(value[:10]) if value else None
        except ValueError:
            return None

    def _dt(value: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        except (ValueError, AttributeError):
            return None

    try:
        return CallOutcome(
            customer_id=customer_id,
            outcome=OutcomeType(parsed.outcome),
            ptp_date=_d(parsed.ptp_date),
            ptp_amount_inr=parsed.ptp_amount_inr,
            payment_mode=parsed.payment_mode,
            paid_on=_d(parsed.paid_on),
            callback_at=_dt(parsed.callback_at),
            transfer_reason=(
                TransferReason(parsed.transfer_reason)
                if parsed.transfer_reason
                else None
            ),
            transfer_note=parsed.summary,
            captured_by="post_call_extractor",
        )
    except Exception:
        return CallOutcome(
            customer_id=customer_id,
            outcome=OutcomeType.DISPUTE_OR_TRANSFER,
            transfer_reason=TransferReason.OTHER,
            transfer_note=(
                f"Extractor proposed {parsed.outcome} but it was incomplete: "
                f"{parsed.summary}"
            ),
            captured_by="post_call_extractor",
        )
