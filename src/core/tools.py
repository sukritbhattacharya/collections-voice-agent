"""Tools the agent calls to act on the world.

The agent does not narrate what it knows -- it asks. Account figures come from
`get_account_context`, verification happens in `verify_otp`, and the call ends
by calling `log_outcome`. A number the model recalls from prose is a
hallucination waiting to happen; a number returned by a function is either
correct or the function is broken, and a broken function is a failing test.

Schemas are strict so arguments validate exactly. `log_outcome` deliberately
declares every field optional and enforces the per-type requirements in the
handler, because which fields are mandatory depends on the outcome type and
JSON Schema cannot express that cleanly. An invalid call returns an error the
model can read and retry, rather than failing the call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from .outcomes import CallOutcome, OutcomeType, TransferReason
from .policy import CallState, account_context


@dataclass
class ToolEvent:
    """Record of one tool call, for the transcript and for scoring."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_account_context",
        "description": (
            "Retrieve the customer's account details and the product terms you "
            "are allowed to quote. Call this once at the start of every call, "
            "before saying anything about the account. Amounts are included "
            "only after the customer has been verified."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "verify_otp",
        "description": (
            "Verify the customer with the one-time password they read out. "
            "Call this only with a code the customer actually said. On success "
            "you may then state account amounts."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code the customer read out, digits only.",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "note_waiver_request",
        "description": (
            "Record that the customer asked for a late fee waiver, discount or "
            "settlement. This does NOT approve anything -- it routes the "
            "request to a human who can decide. Call it whenever a waiver is "
            "asked for, then tell the customer a colleague will call back."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "what_was_asked": {
                    "type": "string",
                    "description": "In the customer's own terms, briefly.",
                }
            },
            "required": ["what_was_asked"],
            "additionalProperties": False,
        },
    },
    {
        "name": "transfer_to_human",
        "description": (
            "Hand the call to a human agent and stop the collections "
            "conversation. Use immediately for abuse, a medical emergency, or "
            "loss of job or income. Also use for a disputed amount. After "
            "calling this, say only that a colleague will take over."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": [r.value for r in TransferReason],
                    "description": "Which queue this call should go to.",
                },
                "note": {
                    "type": "string",
                    "description": "One line of context for the human agent.",
                },
            },
            "required": ["reason", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "log_outcome",
        "description": (
            "Record the result of the call. Exactly one call per conversation, "
            "at the end. Required fields depend on the outcome: "
            "PROMISE_TO_PAY needs ptp_date and ptp_amount_inr; "
            "ALREADY_PAID needs payment_mode and paid_on; "
            "CALLBACK_REQUEST needs callback_at; "
            "DISPUTE_OR_TRANSFER needs transfer_reason."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [o.value for o in OutcomeType],
                },
                "ptp_date": {
                    "type": ["string", "null"],
                    "description": "Date the customer promised to pay, YYYY-MM-DD.",
                },
                "ptp_amount_inr": {
                    "type": ["integer", "null"],
                    "description": "Amount promised, whole rupees.",
                },
                "payment_mode": {
                    "type": ["string", "null"],
                    "description": "How they paid, e.g. UPI, NEFT, net banking.",
                },
                "paid_on": {
                    "type": ["string", "null"],
                    "description": "Date they say they paid, YYYY-MM-DD.",
                },
                "callback_at": {
                    "type": ["string", "null"],
                    "description": "When to call back, ISO 8601.",
                },
                "transfer_reason": {
                    "type": ["string", "null"],
                    "enum": [r.value for r in TransferReason] + [None],
                },
                "summary": {
                    "type": "string",
                    "description": "One sentence on what was agreed.",
                },
            },
            "required": [
                "outcome", "ptp_date", "ptp_amount_inr", "payment_mode",
                "paid_on", "callback_at", "transfer_reason", "summary",
            ],
            "additionalProperties": False,
        },
    },
]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class ToolRegistry:
    """Executes tool calls against one call's state."""

    state: CallState
    events: list[ToolEvent] = field(default_factory=list)
    outcome: CallOutcome | None = None
    model: str | None = None
    agent_version: str = "v3"

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            result = {"error": f"unknown tool {name!r}"}
        else:
            try:
                result = handler(**arguments)
            except TypeError as exc:
                result = {"error": f"bad arguments: {exc}"}
        self.events.append(ToolEvent(name=name, arguments=arguments, result=result))
        return result

    # -- handlers ---------------------------------------------------------

    def _tool_get_account_context(self) -> dict[str, Any]:
        return account_context(self.state)

    def _tool_verify_otp(self, code: str) -> dict[str, Any]:
        if self.state.otp_locked_out:
            return {
                "verified": False,
                "locked_out": True,
                "instruction": (
                    "Too many attempts. Do not offer verification again. "
                    "Continue the call without disclosing any amount."
                ),
            }
        ok = self.state.verify_otp(code)
        if ok:
            return {
                "verified": True,
                "instruction": "You may now state the amounts on this account.",
            }
        return {
            "verified": False,
            "attempts_used": self.state.otp_attempts,
            "attempts_remaining": max(
                0, CallState.MAX_OTP_ATTEMPTS - self.state.otp_attempts
            ),
            "instruction": "That code did not match. Ask them to read it again.",
        }

    def _tool_note_waiver_request(self, what_was_asked: str) -> dict[str, Any]:
        self.state.waiver_requested = True
        return {
            "noted": True,
            "approved": False,
            "instruction": (
                "Logged for human review. Tell the customer it has been noted "
                "and a colleague will call back. Do not approve it yourself "
                "and do not suggest it is likely to be approved."
            ),
        }

    def _tool_transfer_to_human(self, reason: str, note: str) -> dict[str, Any]:
        self.state.transfer_requested = True
        self.state.transfer_reason = reason
        return {
            "transferring": True,
            "reason": reason,
            "instruction": (
                "Stop the collections conversation. Acknowledge briefly, say a "
                "colleague will take over, then call log_outcome with "
                "DISPUTE_OR_TRANSFER and end."
            ),
        }

    def _tool_log_outcome(
        self,
        outcome: str,
        ptp_date: str | None = None,
        ptp_amount_inr: int | None = None,
        payment_mode: str | None = None,
        paid_on: str | None = None,
        callback_at: str | None = None,
        transfer_reason: str | None = None,
        summary: str = "",
    ) -> dict[str, Any]:
        try:
            self.outcome = CallOutcome(
                customer_id=self.state.account.customer_id,
                outcome=OutcomeType(outcome),
                ptp_date=_parse_date(ptp_date),
                ptp_amount_inr=ptp_amount_inr,
                payment_mode=payment_mode,
                paid_on=_parse_date(paid_on),
                callback_at=_parse_datetime(callback_at),
                transfer_reason=(
                    TransferReason(transfer_reason) if transfer_reason else None
                ),
                transfer_note=summary or None,
                waiver_requested=self.state.waiver_requested,
                otp_verified=self.state.otp_verified,
                guardrail_hits=list(self.state.guardrail_hits),
                model=self.model,
                agent_version=self.agent_version,
            )
        except (ValidationError, ValueError) as exc:
            # Hand the problem back so the model can fix its own call. A
            # rejected outcome is recoverable; a silently malformed one is not.
            return {
                "logged": False,
                "error": str(exc).split("\n")[1] if "\n" in str(exc) else str(exc),
                "instruction": (
                    "The outcome was not accepted. Ask the customer for the "
                    "missing detail, then call log_outcome again."
                ),
            }
        return {"logged": True, "outcome": outcome, "call_id": self.outcome.call_id}
