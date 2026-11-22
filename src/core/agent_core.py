"""The agent. No audio in this module.

This is the only place the conversation logic lives. The voice pipeline and the
evaluation harness are both thin clients of it, which is what makes the
evaluation numbers describe the system that actually ships -- if the harness
drove a copy of the prompt, every figure it produced would be about software
nobody runs.

Three configurations are defined so the contribution of each change is
measurable separately:

    v1  the original prompt, outcome logging only
    v2  rewritten prompt, facts via tools          (what prompting buys)
    v3  v2 plus the deterministic guardrails       (what architecture buys)

v1 -> v2 bundles two changes (prompt and fact tools) and that is stated rather
than hidden. v2 -> v3 is a clean single variable.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .guardrails import input_tripwire
from .guardrails.numerics import numbers_spoken
from .guardrails.speech import verbalise as verbalise_identifiers
from .guardrails.transcription import repair as repair_transcription
from .guardrails.output_filter import check as filter_output
from .outcomes import CallOutcome, OutcomeType, TransferReason, deliver
from .policy import (
    INTEREST_PCT_MONTHLY,
    ISSUER_HELPLINE,
    ISSUER_NAME,
    LATE_FEE_INR,
    LATE_FEE_THRESHOLD_INR,
    PAYMENT_REFLECT_WORKING_DAYS,
    Account,
    CallState,
    account_figures,
    account_context,
    compute_late_fee,
    opening_line,
    protected_amounts,
)
from .tools import TOOL_DEFINITIONS, ToolEvent, ToolRegistry

PROMPTS_DIR = Path(__file__).parent / "prompts"

#: Hard ceiling on model round-trips per customer turn. A model that loops on
#: tool calls is a bug, and on a live call it is dead air.
MAX_TOOL_ROUNDS = 6

#: Replies are one or two sentences. This is a backstop, not a target.
MAX_TOKENS = 1024


@dataclass(frozen=True)
class VersionConfig:
    prompt_file: str
    tool_names: tuple[str, ...]
    tripwire: bool
    output_filter: bool
    post_call_extractor: bool


ALL_TOOLS = tuple(t["name"] for t in TOOL_DEFINITIONS)

VERSIONS: dict[str, VersionConfig] = {
    # Outcome logging only: the baseline prompt knows nothing about tools, but
    # without log_outcome it would score zero on outcome capture by
    # construction, which measures the harness rather than the prompt.
    "v1": VersionConfig("v1_baseline.md", ("log_outcome",), False, False, False),
    "v2": VersionConfig("v2_rewrite.md", ALL_TOOLS, False, False, False),
    "v3": VersionConfig("v2_rewrite.md", ALL_TOOLS, True, True, True),
}


@dataclass
class AgentTurn:
    """One thing the agent says, plus what happened while producing it."""

    text: str
    tool_events: list[ToolEvent] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    latency_ms: int = 0
    forced_transfer: str | None = None
    call_ended: bool = False


class LLMClient(Protocol):
    """Minimal surface the agent needs, so the model is swappable and the
    conversation loop is testable without a network call."""

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any: ...


class AnthropicClient:
    """Claude, through the official SDK."""

    def __init__(self, model: str, *, effort: str = "low") -> None:
        from anthropic import Anthropic

        self._client = Anthropic()
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        # Voice is latency-bound. Low effort keeps time-to-first-token down;
        # whether it costs compliance accuracy is an empirical question the
        # evaluation answers, not an assumption made here.
        self.effort = effort

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": self.effort},
        )
        # Accumulated so a run can report what it actually cost, rather than
        # what a pricing page suggests it should have.
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        return response


# After the outcome is logged the customer gets a few turns to raise anything
# else. If the model never calls `end_call` -- it forgot, or it is answering
# something at length -- the call closes anyway. A model that forgets to hang
# up must not be able to leave the line open. See D-049.
#: Turns the customer still gets after the outcome is captured.
#:
#: This is a backstop against a model that forgets to call `end_call`, not a
#: budget for the customer's remaining questions. At 4 it was the latter: two
#: of three long scenarios ended with `close_not_confirmed` while the customer
#: was still mid-question, which is the premature hang-up D-044 set out to
#: avoid. The real ceiling on call length is MAX_CALL_SEC in the voice layer,
#: which is wall-clock and cannot be talked past. See D-054.
MAX_TURNS_AFTER_OUTCOME = 12

#: How many times the agent re-asks before giving up on a silent line. Two is
#: what a person does: ask again, check they are there, then stop. A third
#: attempt to a line nobody is on is just a machine talking to itself, and on
#: a call that is already unwelcome it reads as harassment.
MAX_SILENCE_PROMPTS = 2

#: How many turns a call may run after the agent has handed over. A promise
#: to pay is the bank's business finishing while the customer's may not be,
#: so that case deliberately stays open (MAX_TURNS_AFTER_OUTCOME). A transfer
#: is not the same event: the agent has just said a colleague will take over,
#: so it has nothing left to do and nothing left to ask. Two turns is enough
#: for the customer to say "all right" and be thanked. See D-074.
MAX_TURNS_AFTER_TRANSFER = 2

#: Spoken verbatim when the line has been silent through every re-prompt.
#: Deterministic rather than generated: it is the last thing the customer may
#: hear, it must not invent a commitment nobody made, and a model asked to
#: improvise a goodbye to silence has been observed to summarise a call that
#: did not happen.
SILENCE_SIGN_OFF = (
    "I can't hear anything, so I'll leave it there and try you another time. "
    "Thank you."
)


def _without_thinking(blocks: list[Any]) -> list[Any]:
    """Drop reasoning blocks before they enter the stored history.

    A thinking block carries a signature bound to the exact conversation
    prefix that produced it. This agent mutates its own prefix by design: the
    output filter rewrites what was said (D-035) and the tripwire inserts an
    operator instruction mid-conversation (L3). Either one invalidates every
    signature after it, and the next turn fails with

        Invalid `signature` in `thinking` block. The block is bound to a
        different conversation.

    Reasoning that cannot survive the guardrails is reasoning this system
    cannot keep. See D-047.
    """
    return [
        b for b in blocks
        if getattr(b, "type", None) not in ("thinking", "redacted_thinking")
    ]


class CollectionsAgent:
    """One call."""

    def __init__(
        self,
        account: Account,
        *,
        version: str = "v3",
        client: LLMClient | None = None,
        model: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        if version not in VERSIONS:
            raise ValueError(f"unknown version {version!r}")
        self.version = version
        self.config = VERSIONS[version]
        # An injected client carries its own identity (a stub, or a model
        # pinned by the eval runner). Reporting AGENT_MODEL regardless would
        # put a model name on results it never produced.
        self.model = (
            model
            or getattr(client, "model", None)
            or os.getenv("AGENT_MODEL", "claude-haiku-5-5")
        )
        self.client = client or AnthropicClient(self.model)
        self.webhook_url = webhook_url

        self.state = CallState(account=account)
        #: Whether this account attracts the late fee at all, from the
        #: balance rather than from anything the model says. Read by the
        #: output filter, which must be able to tell a correct callback
        #: promise from a misleading one on turn one. See D-058.
        self.no_late_fee = compute_late_fee(account.outstanding_inr) == 0
        #: Digit sequences this call may read out that are identifiers rather
        #: than quantities, so they are spoken one digit at a time. Amounts
        #: are deliberately absent: place value is correct for those.
        self.spoken_ids: tuple[str, ...] = (
            account.card_last4,
            account.otp,
            ISSUER_HELPLINE,
        )
        self.registry = ToolRegistry(
            state=self.state, model=self.model, agent_version=version
        )
        self.messages: list[dict[str, Any]] = []
        self.transcript: list[dict[str, str]] = []
        self.turn_latencies: list[int] = []
        self.started_at = time.monotonic()
        self.ended = False
        # The voice framework can call into the core speculatively and from
        # more than one thread (preemptive generation). Two turns interleaving
        # their appends to `self.messages` produces a history that belongs to
        # neither of them. See D-047.
        self._turn_lock = threading.Lock()
        self._turns_after_outcome = 0
        self._turns_after_transfer = 0
        self.extractor_error: str | None = None
        #: Figures the customer has volunteered. Echoing one back is correct
        #: call handling, not a disclosure.
        self.customer_stated: set[str] = set()

        self._system = self._build_system_prompt()
        self._tools = [
            t for t in TOOL_DEFINITIONS if t["name"] in self.config.tool_names
        ]

    # -- prompt -----------------------------------------------------------

    def _build_system_prompt(self) -> str:
        text = (PROMPTS_DIR / self.config.prompt_file).read_text(encoding="utf-8")
        today = date.today()
        return text.format(
            issuer=ISSUER_NAME,
            reflect_days=PAYMENT_REFLECT_WORKING_DAYS,
            today=today.isoformat(),
            weekday=today.strftime("%A"),
            # Product terms, substituted rather than written into the prompt
            # text, so a different issuer is a config change. These are the
            # same constants the output filter checks the spoken line against,
            # which is what makes "no figure in the prompt is a figure the
            # filter does not know" true. See D-061.
            interest_pct=INTEREST_PCT_MONTHLY,
            late_fee=int(LATE_FEE_INR),
            late_fee_threshold=f"{int(LATE_FEE_THRESHOLD_INR):,}",
        )

    # -- conversation -----------------------------------------------------

    def open_call(self) -> AgentTurn:
        """The agent speaks first. This is an outbound call.

        The greeting is templated and the account context is fetched
        directly, so the first word is spoken after one text-to-speech call
        rather than after two model round-trips. Measured at roughly 1.8
        seconds saved on the opening -- the point in a call where silence
        costs the most.

        The model's history is seeded with both, so from the customer's first
        reply onward it behaves exactly as though it had produced the greeting
        and called the tool itself.
        """
        import json as _json

        greeting = opening_line(self.state.account)
        context = account_context(self.state)

        # Order matters, and the API enforces it: a system message may only
        # follow a user message. Seeding user -> assistant -> system reads
        # naturally but is rejected with a 400 on the *next* turn, which is
        # why this broke only once a customer replied. See D-041.
        self.messages.append(
            {"role": "user", "content": "The call has connected."}
        )
        self.messages.append(
            {
                "role": "system",
                "content": (
                    "Account context for this call, which you do not need to "
                    "fetch again:\n"
                    f"{_json.dumps(context, default=str)}\n"
                    "Greet the customer and ask them to confirm their "
                    "identity before discussing the account."
                ),
            }
        )
        self.messages.append({"role": "assistant", "content": greeting})

        self.transcript.append(
            {"role": "agent", "text": greeting,
             "otp_verified": self.state.otp_verified}
        )
        return AgentTurn(text=greeting, latency_ms=0)

    def respond(self, customer_text: str) -> AgentTurn:
        """Handle one customer utterance."""
        with self._turn_lock:
            if not customer_text or not customer_text.strip():
                raise ValueError("customer_text is empty; treat silence as a hang-up")

            # Recognition artefacts are repaired before the model reads the
            # turn, but the transcript keeps what recognition actually
            # produced. See D-051 and guardrails/transcription.py.
            heard, repair_note = repair_transcription(customer_text)
            entry: dict[str, Any] = {
                "role": "customer",
                "text": customer_text,
                "otp_verified": self.state.otp_verified,
            }
            if repair_note:
                entry["repaired_to"] = heard
                self.state.transcription_repairs.append(repair_note)
            self.transcript.append(entry)

            self.messages.append({"role": "user", "content": heard})
            self.customer_stated |= numbers_spoken(heard)

            forced: str | None = None
            if self.config.tripwire:
                hit = input_tripwire.scan(heard)
                if hit and not self.state.transfer_requested:
                    forced = hit.reason
                    self.state.transfer_requested = True
                    self.state.transfer_reason = hit.reason
                    self.state.guardrail_hits.append(f"tripwire:{hit.trigger_id}")
                    # Delivered as a mid-conversation system message: it reaches the
                    # model as an operator instruction rather than as something the
                    # customer appears to have said, and it leaves the cached
                    # prefix intact.
                    self.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"OPERATOR: the customer has disclosed {hit.reason}. "
                                "Stop the collections conversation now. Do not ask "
                                "for payment or a date. Acknowledge briefly and "
                                "with warmth, call transfer_to_human with reason "
                                f"{hit.reason}, then call log_outcome with "
                                "DISPUTE_OR_TRANSFER."
                            ),
                        }
                    )

            turn = self._generate()
            turn.forced_transfer = forced
            return turn

    def _generate(self, *, kickoff: str | None = None) -> AgentTurn:
        if kickoff:
            self.messages.append({"role": "user", "content": kickoff})

        started = time.perf_counter()
        events: list[ToolEvent] = []
        text = ""

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.complete(
                system=self._system, messages=self.messages, tools=self._tools
            )
            spoken_blocks = _without_thinking(response.content)
            if not spoken_blocks:
                # Reasoning only, nothing said and nothing called. Appending an
                # empty assistant turn would be rejected outright.
                break
            self.messages.append(
                {"role": "assistant", "content": spoken_blocks}
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()

            if not tool_uses:
                break

            results = []
            for block in tool_uses:
                result = self.registry.execute(block.name, dict(block.input))
                events.append(self.registry.events[-1])
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _as_text(result),
                    }
                )
            # All results go back in one user message. Splitting them teaches
            # the model to stop calling tools in parallel.
            self.messages.append({"role": "user", "content": results})

            if text:
                break

        latency_ms = int((time.perf_counter() - started) * 1000)
        self.turn_latencies.append(latency_ms)

        violations: list[str] = []
        if self.config.output_filter and text:
            result = filter_output(
                text,
                protected_values=protected_amounts(self.state.account),
                otp_verified=self.state.otp_verified,
                customer_stated=tuple(self.customer_stated),
                account_figures=account_figures(self.state.account),
                call_flags={
                    # Known from the balance the moment the call opens, so
                    # the filter never has to wait for the model to call a
                    # tool before it can tell this account from one that
                    # does carry the fee.
                    "late_fee_not_owed": self.no_late_fee,
                    "waiver_on_nonexistent_fee": (
                        self.state.waiver_on_nonexistent_fee
                    ),
                },
            )
            if result.blocked:
                violations = [str(v) for v in result.violations]
                self.state.guardrail_hits.extend(violations)
                text = result.text
                # The replacement is what was said, so the model's own history
                # must reflect it -- otherwise it builds on words the customer
                # never heard.
                self._rewrite_last_assistant_text(text)

        # After the filter, never before: the filter matches this account's
        # protected figures as digit strings, so turning digits into words
        # first would hand an amount a way past it. See D-062.
        speech_notes: list[str] = []
        if text:
            text, speech_notes = verbalise_identifiers(text, self.spoken_ids)

        if text:
            entry: dict[str, Any] = {
                "role": "agent",
                "text": text,
                "otp_verified": self.state.otp_verified,
            }
            if speech_notes:
                entry["verbalised"] = speech_notes
            # Which turn a guardrail rewrote, not just that one did somewhere
            # in the call. `guardrail_hits` answers "did this call breach
            # anything"; reviewing a call needs "on which sentence", and
            # reconstructing that by eye from a 30-turn transcript is how a
            # reviewer stops reviewing.
            if violations:
                entry["blocked"] = violations
            self.transcript.append(entry)

        ended = self._should_end()
        self.ended = self.ended or ended

        return AgentTurn(
            text=text,
            tool_events=events,
            violations=violations,
            latency_ms=latency_ms,
            call_ended=ended,
        )

    def reprompt(self) -> AgentTurn | None:
        """Ask again, because the customer has said nothing.

        Silence never reaches the core on its own: the conversation loop is
        driven by customer turns, so a customer who says nothing produces no
        turn and the agent waits indefinitely. The voice layer notices the gap
        and calls this. See D-064.

        Returns `None` once the re-prompt budget is spent; the caller should
        speak `SILENCE_SIGN_OFF` and end the call.

        A re-prompt is not a customer turn. It appends an agent turn to the
        transcript and nothing to the customer side, so it inflates neither
        `turn_count` nor the post-outcome ceiling -- a silent customer must not
        be able to end the call early by being quiet, nor hold it open.
        """
        if self.state.silence_prompts >= MAX_SILENCE_PROMPTS:
            self.state.ended_on_silence = True
            self.state.call_closed = True
            self.ended = True
            self.transcript.append({
                "role": "agent",
                "text": SILENCE_SIGN_OFF,
                "otp_verified": self.state.otp_verified,
                "after_silence": True,
            })
            return None

        self.state.silence_prompts += 1
        first = self.state.silence_prompts == 1
        self.messages.append({
            "role": "user",
            "content": (
                "[SYSTEM: The line has been silent for several seconds. The "
                "customer has said nothing -- they may not have heard you, or "
                "may have put the phone down. "
                + (
                    "Ask your last question again, in fewer words. Do not "
                    "greet them again, do not apologise at length, and do not "
                    "add anything new. One short sentence."
                    if first else
                    "Check whether they are still there, in one short "
                    "sentence, and say you will try another time if not."
                )
                + " This is an instruction, not something the customer said.]"
            ),
        })
        turn = self._generate()
        if turn.text:
            self.transcript[-1]["after_silence"] = True
        return turn

    def _should_end(self) -> bool:
        """Whether the call should hang up after this turn.

        Logging the outcome used to end the call immediately. That conflates
        two different events: the bank's business being finished, and the
        customer being finished. Hanging up the moment a promise to pay is
        captured is abrupt on a call that is already unwelcome, and it denies
        the customer the one question they rang in their head to ask.

        So the agent asks, and ends when they decline -- with a ceiling, so a
        model that forgets to call `end_call` cannot hold the line open.
        """
        if self.state.call_closed:
            return True

        # A hand-over ends the call, shortly. Without this the line stayed
        # open on the one kind of call where staying is worst: a customer who
        # has just disclosed job loss and a hospital heard "a colleague will
        # take over from here" four times, twice of them prompted by the
        # silence watchdog, because nothing told the loop the agent was done.
        if self.state.transfer_requested:
            self._turns_after_transfer += 1
            if self._turns_after_transfer > MAX_TURNS_AFTER_TRANSFER:
                return True

        if self.registry.outcome is None:
            return False
        self._turns_after_outcome += 1
        if self._turns_after_outcome > MAX_TURNS_AFTER_OUTCOME:
            self.state.guardrail_hits.append("close_not_confirmed")
            return True
        return False

    def _rewrite_last_assistant_text(self, replacement: str) -> None:
        for message in reversed(self.messages):
            if message["role"] != "assistant":
                continue
            blocks = message["content"]
            if isinstance(blocks, list):
                for block in blocks:
                    if getattr(block, "type", None) == "text":
                        try:
                            block.text = replacement
                        except (AttributeError, ValueError):
                            pass
                        return
            return

    # -- closing ----------------------------------------------------------

    def note_wrap_up(self, text: str) -> None:
        """Record the line the voice layer speaks when the clock runs out.

        It is spoken through the session rather than generated by the core,
        so without this the transcript just stops and the record cannot tell
        a truncated call from a crashed one. See D-073.
        """
        self.state.ended_on_ceiling = True
        self.transcript.append({
            "role": "agent",
            "text": text,
            "otp_verified": self.state.otp_verified,
            "after_ceiling": True,
        })

    async def finish(
        self,
        *,
        client: dict[str, Any] | None = None,
        latency: dict[str, Any] | None = None,
    ) -> CallOutcome:
        """Close the call and deliver the outcome.

        If the model never logged one -- it was cut off, the customer hung up,
        it simply forgot -- an outcome is derived from the transcript. "Every
        call ends with a structured outcome" has to be true by construction,
        not by hope.
        """
        outcome = self.registry.outcome
        if outcome is None and self.config.post_call_extractor:
            outcome = self._extract_outcome()
        if outcome is None:
            outcome = self._fallback_outcome()

        outcome.duration_sec = int(time.monotonic() - self.started_at)
        outcome.turn_count = len(
            [t for t in self.transcript if t["role"] == "customer"]
        )
        outcome.transcript = self.transcript
        outcome.guardrail_hits = list(self.state.guardrail_hits)
        outcome.waiver_requested = self.state.waiver_requested
        outcome.waiver_on_nonexistent_fee = (
            self.state.waiver_on_nonexistent_fee
        )
        outcome.otp_verified = self.state.otp_verified
        outcome.ended_on_ceiling = self.state.ended_on_ceiling
        outcome.model = self.model
        outcome.agent_version = self.version
        if self.turn_latencies:
            ordered = sorted(self.turn_latencies)
            outcome.latency.p50_ms = ordered[len(ordered) // 2]
            outcome.latency.p95_ms = ordered[min(
                len(ordered) - 1, int(len(ordered) * 0.95)
            )]
            outcome.latency.turns_measured = len(ordered)
            outcome.latency.turns_ms = list(self.turn_latencies)

        # Applied before delivery, not after. Mutating the outcome once it has
        # already been POSTed leaves the caller holding a correct object and
        # the CRM holding a wrong one -- which is how every voice call landed
        # in the sink labelled `surface: "text"`. See D-042.
        if client:
            if client.get("surface"):
                outcome.client.surface = client["surface"]
            outcome.client.platform = client.get("platform")
            outcome.client.browser = client.get("browser")
        if latency:
            # The voice pipeline measures end-of-speech to first audio out,
            # which is the number M5 is defined on. It supersedes the core's
            # own model-call timing when present.
            outcome.latency.p50_ms = latency.get("p50_ms")
            outcome.latency.p95_ms = latency.get("p95_ms")
            outcome.latency.turns_measured = latency.get("turns_measured") or 0
            outcome.latency.turns_ms = list(latency.get("turns_ms") or [])

        await deliver(outcome, webhook_url=self.webhook_url)
        return outcome

    def _extract_outcome(self) -> CallOutcome | None:
        """Derive an outcome from the transcript after the fact."""
        from .extractor import extract_outcome

        try:
            return extract_outcome(
                transcript=self.transcript,
                customer_id=self.state.account.customer_id,
                model=os.getenv("EXTRACTOR_MODEL", "claude-haiku-5-5"),
            )
        except Exception as exc:  # noqa: BLE001
            # Swallowing this silently once already cost a debugging cycle: the
            # fallback looked like the model forgetting to log, when the
            # extractor was in fact raising on every call.
            self.extractor_error = f"{type(exc).__name__}: {exc}"
            return None

    def _fallback_outcome(self) -> CallOutcome:
        """Last resort. Never raises -- a call must always produce a record."""
        reason = TransferReason.OTHER
        if self.state.transfer_reason:
            try:
                reason = TransferReason(self.state.transfer_reason)
            except ValueError:
                pass
        return CallOutcome(
            customer_id=self.state.account.customer_id,
            outcome=OutcomeType.DISPUTE_OR_TRANSFER,
            transfer_reason=reason,
            transfer_note="No outcome captured during the call.",
            captured_by="fallback",
        )


def _as_text(result: dict[str, Any]) -> str:
    import json

    return json.dumps(result, default=str)
