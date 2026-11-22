"""Adapter: LiveKit's pipeline talks to our agent core.

LiveKit's `AgentSession` would happily run its own model loop and its own tool
calling. Letting it do that would mean two brains -- one driving the demo and
one being measured by the evaluation harness -- and every number in the
the solution brief would describe the wrong system.

So the pipeline keeps the jobs it is good at (voice activity detection, turn
detection, interruption, transport) and `CollectionsAgent` keeps every
decision: the prompt, the tools, the guardrails, the outcome. This adapter is
the seam, and it is deliberately thin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from livekit.agents import llm

from src.core.agent_core import CollectionsAgent
from src.voice.telemetry import CallTelemetry

logger = logging.getLogger("collections.voice")


class CoreBackedLLM(llm.LLM):
    """Presents `CollectionsAgent` to LiveKit as if it were a model."""

    def __init__(self, agent: CollectionsAgent, telemetry: CallTelemetry) -> None:
        super().__init__()
        self.agent = agent
        self.telemetry = telemetry

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[Any] | None = None,
        conn_options: Any = None,
        **kwargs: Any,
    ) -> llm.LLMStream:
        return _CoreStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


def _last_user_text(chat_ctx: llm.ChatContext) -> str:
    """What the customer just said, as the transcriber heard it."""
    for item in reversed(list(chat_ctx.items)):
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", None)
        if isinstance(content, list):
            parts = [c for c in content if isinstance(c, str)]
            if parts:
                return " ".join(parts).strip()
        elif isinstance(content, str):
            return content.strip()
    return ""


class _CoreStream(llm.LLMStream):
    async def _run(self) -> None:
        adapter: CoreBackedLLM = self._llm  # type: ignore[assignment]
        agent = adapter.agent
        said = _last_user_text(self._chat_ctx)

        timing = adapter.telemetry.turns[-1] if adapter.telemetry.turns else None
        if timing is not None:
            timing.mark("stt_final")

        if not said:
            # Silence. Nothing to answer, and an empty turn would be rejected
            # by the API anyway.
            return

        failed = False
        try:
            # The core is synchronous. Running it inline would block the event
            # loop and stall audio for every other participant.
            turn = await asyncio.to_thread(agent.respond, said)
        except Exception:
            logger.exception("agent core failed on a turn: %r", said)
            turn = None
            failed = True

        if timing is not None:
            timing.mark("llm_first_token")

        if turn is not None and turn.text:
            text = turn.text
        elif failed:
            # Deliberately *not* the same sentence as a transcription failure.
            # For two calls the agent said "Sorry, I didn't catch that" while
            # the transcriber was working perfectly, and the identical wording
            # sent the investigation at speech recognition instead of at the
            # core. A fallback that disguises its own cause costs more than the
            # call it saves. See D-041, D-047.
            agent.state.guardrail_hits.append("core_error")
            text = "Sorry, I'm having trouble on my end. Could you say that once more?"
        else:
            text = "Sorry, I didn't catch that. Could you say it again?"

        if turn is not None:
            if turn.forced_transfer:
                logger.info("tripwire fired: %s", turn.forced_transfer)
            for violation in turn.violations:
                logger.warning("guardrail blocked an utterance: %s", violation)

        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=f"core-{len(agent.transcript)}",
                delta=llm.ChoiceDelta(role="assistant", content=text),
            )
        )
