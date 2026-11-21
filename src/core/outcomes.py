"""Call outcomes: the structured record a CRM picks up after every call.

A call that produces no outcome did not happen, as far as the collections team
is concerned. This module defines what a valid outcome looks like, refuses to
build an invalid one, and delivers it.

Validation is deliberately strict. A missing promise-to-pay date is not a
degraded record to be patched downstream -- it is a defect, and it should fail
here, loudly, where a test can see it.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, model_validator

OUTCOMES_LOG = Path("results/outcomes.jsonl")

#: A promise to pay further out than this is accepted but flagged for review.
#: Early-stage delinquency work is about recovering inside the cycle; a date
#: three months out is not a commitment, it is a way of ending the call.
PTP_REVIEW_HORIZON_DAYS = 30


class OutcomeType(StrEnum):
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    ALREADY_PAID = "ALREADY_PAID"
    CALLBACK_REQUEST = "CALLBACK_REQUEST"
    DISPUTE_OR_TRANSFER = "DISPUTE_OR_TRANSFER"


class TransferReason(StrEnum):
    """Why a call left the agent. Each maps to a different human queue."""

    ABUSE = "ABUSE"
    MEDICAL_EMERGENCY = "MEDICAL_EMERGENCY"
    JOB_LOSS = "JOB_LOSS"
    DISPUTE = "DISPUTE"
    WAIVER_REQUEST = "WAIVER_REQUEST"
    WRONG_PERSON = "WRONG_PERSON"
    OTHER = "OTHER"


class LatencyStats(BaseModel):
    """Per-turn response latency. Absent for text-mode runs."""

    p50_ms: int | None = None
    p95_ms: int | None = None
    turns_measured: int = 0


class ClientInfo(BaseModel):
    """Where the call came from. Lets a device-specific failure show up in the
    data rather than as an anecdote."""

    surface: str = "text"  # text | web
    platform: str | None = None  # ios | android | macos | windows | linux
    browser: str | None = None


class CallOutcome(BaseModel):
    """The payload delivered to the CRM at the end of every call."""

    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    outcome: OutcomeType

    # Promise to pay
    ptp_date: date | None = None
    ptp_amount_inr: int | None = None
    ptp_beyond_horizon: bool = False

    # Already paid
    payment_mode: str | None = None
    paid_on: date | None = None

    # Callback
    callback_at: datetime | None = None

    # Transfer / dispute
    transfer_reason: TransferReason | None = None
    transfer_note: str | None = None

    # Always present
    waiver_requested: bool = False
    #: The waiver was asked for against a fee this account is not
    #: charged. Routing it as an ordinary request wastes a human call.
    waiver_on_nonexistent_fee: bool = False
    otp_verified: bool = False
    guardrail_hits: list[str] = Field(default_factory=list)
    duration_sec: int | None = None
    turn_count: int = 0
    agent_version: str = "v3"
    model: str | None = None
    latency: LatencyStats = Field(default_factory=LatencyStats)
    client: ClientInfo = Field(default_factory=ClientInfo)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    captured_by: str = "agent"  # agent | post_call_extractor
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _require_fields_for_type(self) -> CallOutcome:
        """Each outcome type carries its own mandatory fields.

        Without this a model can emit PROMISE_TO_PAY with no date and the call
        looks successful while being operationally useless.
        """
        missing: list[str] = []

        if self.outcome is OutcomeType.PROMISE_TO_PAY:
            if self.ptp_date is None:
                missing.append("ptp_date")
            if self.ptp_amount_inr is None:
                missing.append("ptp_amount_inr")
        elif self.outcome is OutcomeType.ALREADY_PAID:
            if not self.payment_mode:
                missing.append("payment_mode")
            if self.paid_on is None:
                missing.append("paid_on")
        elif self.outcome is OutcomeType.CALLBACK_REQUEST:
            if self.callback_at is None:
                missing.append("callback_at")
        elif self.outcome is OutcomeType.DISPUTE_OR_TRANSFER:
            if self.transfer_reason is None:
                missing.append("transfer_reason")

        if missing:
            raise ValueError(
                f"{self.outcome} requires {', '.join(missing)}"
            )
        return self

    @model_validator(mode="after")
    def _sanity_check_dates(self) -> CallOutcome:
        """Catch commitments that are not really commitments."""
        today = date.today()

        if self.ptp_date is not None:
            if self.ptp_date < today:
                raise ValueError(f"ptp_date {self.ptp_date} is in the past")
            horizon = today + timedelta(days=PTP_REVIEW_HORIZON_DAYS)
            # Flagged rather than rejected: the customer did say it, and the
            # collections team needs to see that they said it.
            object.__setattr__(
                self, "ptp_beyond_horizon", self.ptp_date > horizon
            )

        if self.paid_on is not None and self.paid_on > today:
            raise ValueError(f"paid_on {self.paid_on} is in the future")

        return self

    @model_validator(mode="after")
    def _amount_is_positive(self) -> CallOutcome:
        if self.ptp_amount_inr is not None and self.ptp_amount_inr <= 0:
            raise ValueError("ptp_amount_inr must be positive")
        return self

    def to_payload(self) -> dict[str, Any]:
        """Wire format. Transcript excluded -- it goes to object storage in a
        real deployment, not inside a CRM webhook body."""
        data = self.model_dump(mode="json", exclude={"transcript"})
        data["transcript_turns"] = len(self.transcript)
        return data


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

def _mirror_locally(outcome: CallOutcome) -> None:
    """Always write to disk, whatever the network does.

    The local mirror is the source of truth for evaluation runs and the reason
    a webhook outage cannot cost us a result.
    """
    OUTCOMES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with OUTCOMES_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(outcome.model_dump(mode="json")) + "\n")


async def deliver(outcome: CallOutcome, *, webhook_url: str | None = None) -> bool:
    """Send the outcome onward. Returns whether the webhook accepted it.

    One retry, then give up. A collections CRM that is down for two consecutive
    requests is not going to be rescued by a third from inside a phone call --
    the local mirror is the safety net, and replay is a batch job.
    """
    _mirror_locally(outcome)

    # An empty string is an explicit "do not deliver" (evaluation runs); None
    # means "use whatever is configured" (live calls).
    url = os.getenv("OUTCOME_WEBHOOK_URL", "") if webhook_url is None else webhook_url
    if not url:
        return False

    payload = outcome.to_payload()
    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in (1, 2):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code < 400:
                    return True
            except httpx.HTTPError:
                pass
            if attempt == 1:
                continue
    return False
