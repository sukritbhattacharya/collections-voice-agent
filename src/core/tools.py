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
from .policy import CallState, account_context, compute_late_fee


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
        "name": "end_call",
        "description": (
            "Hang up. Call this only after you have logged the outcome, asked "
            "the customer whether there is anything else they wanted to ask, "
            "and they have said there is not. Never call it in the same turn "
            "as log_outcome, and never while a question of theirs is "
            "unanswered."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Briefly, why the call is ending now, e.g. 'customer "
                        "confirmed nothing further'."
                    ),
                },
            },
            "required": ["reason"],
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
                    # A nullable enum has to be anyOf: strict schema validation
                    # rejects an enum whose values do not all match a declared
                    # union type.
                    "anyOf": [
                        {"type": "string",
                         "enum": [r.value for r in TransferReason]},
                        {"type": "null"},
                    ],
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

    def _tool_end_call(self, reason: str) -> dict[str, Any]:
        """The customer has nothing further. Close the line."""
        self.state.call_closed = True
        return {"ok": True, "ended": True, "reason": reason}

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
        """Route a waiver request to a human -- and say whether there is one to route.

        A customer can ask to waive a fee that was never charged. On a live
        call against `MB-9023` (balance below the threshold, so no fee is due)
        the agent accepted the premise, logged the request and promised a
        callback about a fee that does not exist. Nothing was factually
        *stated* -- no rule fired, correctly -- but the customer rang off
        believing she owed seven hundred and fifty rupees she did not, and a
        human was committed to calling her back about nothing.

        The model cannot be trusted to check this for itself, so the tool
        checks: the fee is recomputed from the balance here, and the
        instruction the model receives differs by what is actually owed and by
        whether the customer has been verified. See D-058.
        """
        self.state.waiver_requested = True
        fee_applies = compute_late_fee(self.state.account.outstanding_inr) > 0
        self.state.waiver_on_nonexistent_fee = not fee_applies

        if fee_applies:
            instruction = (
                "Logged for human review. Tell the customer it has been noted "
                "and a colleague will call back. Do not approve it yourself "
                "and do not suggest it is likely to be approved."
            )
        elif self.state.otp_verified:
            # Verified, so the balance is theirs to hear: correct the premise.
            instruction = (
                "No late fee has been charged on this account. Say so plainly "
                "-- there is nothing to waive. Do not promise a callback about "
                "a fee that does not exist. Then return to the overdue "
                "minimum payment, which is still due."
            )
        else:
            # Correcting her now would reveal which side of the threshold the
            # balance sits on. Refusing to engage is the only move that is
            # neither a disclosure nor a false impression.
            instruction = (
                "No late fee has been charged on this account, but do NOT say "
                "so yet -- before verification it reveals that the balance is "
                "below the fee threshold. Equally, do not accept that a fee "
                "exists or promise a callback about one. Tell the customer you "
                "cannot discuss what has been applied to the account until you "
                "have verified them, and offer to send the one-time password. "
                "Once they are verified, tell them plainly that no late fee "
                "has been charged."
            )

        return {
            "noted": True,
            "approved": False,
            "late_fee_applies": fee_applies,
            "instruction": instruction,
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
                waiver_on_nonexistent_fee=self.state.waiver_on_nonexistent_fee,
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
