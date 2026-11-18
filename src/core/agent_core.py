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
import time
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .guardrails import input_tripwire
from .guardrails.numerics import numbers_spoken
from .guardrails.output_filter import check as filter_output
from .outcomes import CallOutcome, OutcomeType, TransferReason, deliver
from .policy import (
    ISSUER_NAME,
    PAYMENT_REFLECT_WORKING_DAYS,
    Account,
    CallState,
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
        self.registry = ToolRegistry(
            state=self.state, model=self.model, agent_version=version
        )
        self.messages: list[dict[str, Any]] = []
        self.transcript: list[dict[str, str]] = []
        self.turn_latencies: list[int] = []
        self.started_at = time.monotonic()
        self.ended = False
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
        )

    # -- conversation -----------------------------------------------------

    def open_call(self) -> AgentTurn:
        """The agent speaks first. This is an outbound call."""
        return self._generate(
            kickoff="The call has connected. Greet the customer and begin."
        )

    def respond(self, customer_text: str) -> AgentTurn:
        """Handle one customer utterance."""
        if not customer_text or not customer_text.strip():
            raise ValueError("customer_text is empty; treat silence as a hang-up")
        self.transcript.append({
            "role": "customer",
            "text": customer_text,
            "otp_verified": self.state.otp_verified,
        })
        self.messages.append({"role": "user", "content": customer_text})
        self.customer_stated |= numbers_spoken(customer_text)

        forced: str | None = None
        if self.config.tripwire:
            hit = input_tripwire.scan(customer_text)
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
            self.messages.append(
                {"role": "assistant", "content": response.content}
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
            )
            if result.blocked:
                violations = [str(v) for v in result.violations]
                self.state.guardrail_hits.extend(violations)
                text = result.text
                # The replacement is what was said, so the model's own history
                # must reflect it -- otherwise it builds on words the customer
                # never heard.
                self._rewrite_last_assistant_text(text)

        if text:
            self.transcript.append({
                "role": "agent",
                "text": text,
                "otp_verified": self.state.otp_verified,
            })

        ended = self.registry.outcome is not None
        self.ended = self.ended or ended

        return AgentTurn(
            text=text,
            tool_events=events,
            violations=violations,
            latency_ms=latency_ms,
            call_ended=ended,
        )

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

    async def finish(self) -> CallOutcome:
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
        outcome.otp_verified = self.state.otp_verified
        outcome.model = self.model
        outcome.agent_version = self.version
        if self.turn_latencies:
            ordered = sorted(self.turn_latencies)
            outcome.latency.p50_ms = ordered[len(ordered) // 2]
            outcome.latency.p95_ms = ordered[min(
                len(ordered) - 1, int(len(ordered) * 0.95)
            )]
            outcome.latency.turns_measured = len(ordered)

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
