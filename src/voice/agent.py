"""Voice entrypoint.

Wires speech to the agent core. Everything cognitive -- prompt, tools,
guardrails, outcome -- lives in `src.core`; this file owns only the audio path
and the speech vendors.

    uv run python -m src.voice.agent dev        # connect to a LiveKit room
    uv run python -m src.voice.agent console    # talk from the terminal

Text-to-speech is chosen by TTS_PROVIDER so the Aura-2 / Azure en-IN
comparison is a config change, not a code change. See D-025.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import deepgram, silero

from src.core.agent_core import CollectionsAgent
from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID, STT_KEYTERMS
from src.voice.core_llm import CoreBackedLLM
from src.voice.telemetry import CallTelemetry

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("collections.voice")


def build_stt() -> deepgram.STT:
    """Streaming transcription tuned for this call type.

    `language="multi"` is the documented code-switching mode and the reason
    Deepgram was chosen: the brief says customers reply in a mix of Hindi and
    English inside the same sentence, which is a different problem from
    detecting which language a speaker is using.

    Keyterms bias recognition toward collections vocabulary, so payment rails
    transcribe as "NEFT" rather than something phonetically close.
    """
    return deepgram.STT(
        model="nova-3",
        language="multi",
        interim_results=True,
        smart_format=True,
        punctuate=True,
        # Collections callers pause mid-sentence while finding a statement or
        # calculating. Too short and the agent talks over them.
        endpointing_ms=400,
        keyterm=list(STT_KEYTERMS),
    )


def build_tts():
    """Aura-2 by default; Azure en-IN for the voice comparison."""
    provider = os.getenv("TTS_PROVIDER", "deepgram").lower()

    if provider == "azure":
        from livekit.plugins import azure

        voice = os.getenv("AZURE_TTS_VOICE", "en-IN-NeerjaNeural")
        logger.info("text-to-speech: azure %s", voice)
        return azure.TTS(
            voice=voice,
            speech_key=os.environ["AZURE_SPEECH_KEY"],
            speech_region=os.getenv("AZURE_SPEECH_REGION", "centralindia"),
        )

    voice = os.getenv("DEEPGRAM_TTS_VOICE", "aura-2-thalia-en")
    logger.info("text-to-speech: deepgram %s", voice)
    return deepgram.TTS(model=voice)


def prewarm(proc) -> None:
    """Load the voice activity detector once per worker, not once per call.

    Silero takes roughly a second to initialise. Doing that inside the
    entrypoint charges every call for it, as dead air before the agent can
    speak. Prewarming moves the cost to worker startup, where nobody is
    listening.
    """
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    customer_id = os.getenv("CALL_CUSTOMER_ID", DEFAULT_CUSTOMER_ID)
    account = ACCOUNTS[customer_id]
    version = os.getenv("AGENT_VERSION", "v3")

    core = CollectionsAgent(account=account, version=version)
    telemetry = CallTelemetry()

    logger.info(
        "calling %s (%s), %s days past due, agent %s on %s",
        account.name, account.customer_id, account.days_past_due, version, core.model,
    )

    session = AgentSession(
        stt=build_stt(),
        llm=CoreBackedLLM(core, telemetry),
        tts=build_tts(),
        vad=ctx.proc.userdata.get("vad") or silero.VAD.load(),
    )

    @session.on("user_input_transcribed")
    def _on_transcript(event) -> None:
        # Start the clock when the customer stops speaking, not when our
        # pipeline gets round to them.
        if getattr(event, "is_final", False):
            telemetry.begin_turn()

    @session.on("conversation_item_added")
    def _on_item(event) -> None:
        item = getattr(event, "item", None)
        if getattr(item, "role", None) == "assistant" and telemetry.turns:
            telemetry.turns[-1].mark("audio_out")

    await session.start(
        agent=Agent(instructions="Collections agent. Behaviour is owned by the core."),
        room=ctx.room,
    )

    # This is an outbound call: the agent speaks first.
    opening = await asyncio.to_thread(core.open_call)
    await session.say(opening.text)

    try:
        while not core.ended:
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info("call cancelled")
    finally:
        outcome = await core.finish()
        summary = telemetry.summary()
        outcome.latency.p50_ms = summary["p50_ms"]
        outcome.latency.p95_ms = summary["p95_ms"]
        outcome.latency.turns_measured = summary["turns_measured"] or 0
        outcome.client.surface = "web"

        logger.info("outcome: %s (%s)", outcome.outcome, outcome.captured_by)
        logger.info("latency p50/p95: %s / %s ms", summary["p50_ms"], summary["p95_ms"])
        logger.info("stage medians: %s", telemetry.stage_breakdown())
        if core.state.guardrail_hits:
            logger.warning("guardrail hits: %s", core.state.guardrail_hits)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm)
    )
