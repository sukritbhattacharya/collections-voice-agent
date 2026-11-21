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
import json
import logging
import os
import time

from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, silero

from src.core.agent_core import (
    MAX_SILENCE_PROMPTS,
    SILENCE_SIGN_OFF,
    CollectionsAgent,
)
from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID, STT_KEYTERMS
from src.voice.core_llm import CoreBackedLLM
from src.voice.telemetry import CallTelemetry

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("collections.voice")

# A collections call has a 2-3 minute budget (M4). Without a ceiling the agent
# stays on the line as long as the customer keeps talking, which is both a cost
# problem and a compliance one: an open-ended call is an invitation to ask the
# agent things it has no business answering. See D-044.
MAX_CALL_SEC = float(os.getenv("MAX_CALL_SEC", "240"))

#: How long a silent line is left before the agent asks again. Eight seconds
#: is a long pause in conversation and a short one for someone who has walked
#: to find their card. Four felt like interrupting when tried by ear; fifteen
#: -- the framework's own default for marking a user "away" -- is long enough
#: that the customer has concluded the line is dead. See D-064.
SILENCE_SEC = float(os.getenv("SILENCE_SEC", "8"))

#: How the session handles turn-taking.
#:
#: Preemptive generation starts a reply on an interim transcript and discards
#: it if the final differs. It buys roughly a second of perceived latency for
#: a pipeline whose LLM is stateless.
#:
#: Ours is not. The core owns the conversation, so a speculative call is
#: indistinguishable from a real turn: it appends to the history and the
#: discarded turn stays there. Under barge-in -- when interim transcripts
#: change most -- that corrupted the history on every interruption. See D-047.
#:
#: The value is a nested options mapping, not a flag. Passing
#: `preemptive_generation=False` type-checks, reads correctly, and crashes
#: every job at session construction with "'bool' object is not a mapping",
#: so the agent joins the room and never speaks. It lives here, at module
#: level, so a test can hand it to the framework's own resolvers without
#: starting a call. See D-052.
TURN_HANDLING = TurnHandlingOptions(
    preemptive_generation={"enabled": False},
)

WRAP_UP_LINE = (
    "I need to let you go, but thank you for your time. "
    "You can reach us on the number on the back of your card. Goodbye."
)


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
        try:
            from livekit.plugins import azure
        except ImportError as exc:
            raise RuntimeError(
                "TTS_PROVIDER=azure needs the azure extra: "
                "uv sync --extra voice --extra azure"
            ) from exc

        voice = os.getenv("AZURE_TTS_VOICE", "en-IN-NeerjaNeural")

        # A neutral neural voice reads an arrears line flatly, and flat on a
        # debt call reads as a robocall -- which is the opposite of the trust
        # the first two seconds have to earn. Neerja exposes an `empathetic`
        # prosody, and it measured *faster* than her default (281ms against
        # 302ms to first byte). Warmth here costs nothing. See D-048.
        style_name = os.getenv("AZURE_TTS_STYLE", "empathetic")
        style = (
            azure.tts.StyleConfig(
                style=style_name,
                degree=float(os.getenv("AZURE_TTS_STYLE_DEGREE", "1.3")),
            )
            if style_name and style_name.lower() not in ("", "none")
            else NOT_GIVEN
        )

        logger.info("text-to-speech: azure %s style=%s", voice, style_name or "-")
        return azure.TTS(
            voice=voice,
            style=style,
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


def resolve_account(ctx: JobContext):
    """Which customer this call is about.

    The caller's join token carries the account as participant metadata, so a
    demo can switch persona between calls without restarting the worker --
    which matters when someone hands you three personas live and expects a
    call on each. `CALL_CUSTOMER_ID` remains the fallback for headless runs
    and for the smoke test, which mints its own token.

    Resolution is deliberately forgiving: an unrecognised id falls back to the
    default and logs, because losing the job to a KeyError mid-demo is a worse
    outcome than calling the wrong fixture. The web server validates the id
    before minting a token, so a bad value should never reach here. See D-053.
    """
    requested: str | None = None
    for participant in ctx.room.remote_participants.values():
        if not participant.metadata:
            continue
        try:
            requested = json.loads(participant.metadata).get("customer_id")
        except (ValueError, AttributeError):
            continue
        if requested:
            break

    requested = requested or os.getenv("CALL_CUSTOMER_ID") or DEFAULT_CUSTOMER_ID
    if requested not in ACCOUNTS:
        logger.warning(
            "unknown customer %r; falling back to %s", requested, DEFAULT_CUSTOMER_ID
        )
        requested = DEFAULT_CUSTOMER_ID
    return ACCOUNTS[requested]


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    account = resolve_account(ctx)
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
        turn_handling=TURN_HANDLING,
    )

    client_info: dict[str, str] = {}

    @ctx.room.on("data_received")
    def _on_data(packet) -> None:
        if getattr(packet, "topic", "") != "client":
            return
        try:
            payload = json.loads(bytes(packet.data).decode())
        except (ValueError, UnicodeDecodeError):
            return
        if payload.get("type") == "client":
            client_info.update(
                {k: v for k, v in payload.items() if k in ("platform", "browser")}
            )
            logger.info("caller device: %s", client_info)

    @session.on("user_input_transcribed")
    def _on_transcript(event) -> None:
        # Start the clock when the customer stops speaking, not when our
        # pipeline gets round to them.
        if getattr(event, "is_final", False):
            telemetry.begin_turn()

    @session.on("agent_state_changed")
    def _on_agent_state(event) -> None:
        """Mark the *first* audio of the reply, not the last.

        This previously hung off `conversation_item_added`, which fires once
        the utterance has finished playing. That measured how long the agent
        talked: a call that felt responsive reported a p95 of 12,641 ms. M5 is
        defined as end-of-customer-speech to first audio out, so the mark
        belongs on the transition into `speaking`. See D-043.
        """
        if getattr(event, "new_state", None) != "speaking" or not telemetry.turns:
            return
        timing = telemetry.turns[-1]
        if timing.audio_out_ms is None:
            timing.mark("audio_out")

    # -- silence -------------------------------------------------------
    # The conversation loop is driven by customer turns, so a customer who
    # says nothing produces no turn and the agent waits for the call ceiling
    # in silence. Nobody reported this because nobody sat in silence; every
    # test, scripted or human, answers. See D-064.
    #
    # The clock starts when the agent stops speaking, not when the customer
    # last spoke -- what matters is how long they have been left waiting for
    # a reply to a question they were just asked.
    quiet_since: float | None = None
    speaking = False

    @session.on("agent_state_changed")
    def _on_agent_quiet(event) -> None:
        nonlocal quiet_since, speaking
        state = getattr(event, "new_state", None)
        if state == "speaking":
            speaking = True
            quiet_since = None
        elif state == "listening":
            speaking = False
            quiet_since = time.monotonic()

    @session.on("user_input_transcribed")
    def _on_customer_heard(event) -> None:
        nonlocal quiet_since
        # Any speech at all resets the clock, interim included: the customer
        # audibly thinking is not the customer absent, and prompting over
        # someone who has started to answer is worse than waiting.
        quiet_since = None

    await session.start(
        agent=Agent(instructions="Collections agent. Behaviour is owned by the core."),
        room=ctx.room,
    )

    # This is an outbound call: the agent speaks first.
    opening = await asyncio.to_thread(core.open_call)
    await session.say(opening.text)

    # Arm the silence clock here as well as in the state handler. Relying on
    # the handler alone was the first version of this and it never fired once:
    # the handlers were registered after the opening line, by which time the
    # transition into `listening` had already happened, and nothing moves the
    # state again until the customer speaks -- which is the thing being waited
    # for. A control that arms itself on an event that has already passed is
    # not a control. See D-064.
    quiet_since = time.monotonic()

    deadline = time.monotonic() + MAX_CALL_SEC
    timed_out = False
    silent_close = False
    try:
        while not core.ended:
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning("call hit the %.0fs ceiling; wrapping up", MAX_CALL_SEC)
                break

            if (
                not speaking
                and quiet_since is not None
                and time.monotonic() - quiet_since > SILENCE_SEC
            ):
                quiet_since = None  # disarm while we handle it
                turn = await asyncio.to_thread(core.reprompt)
                if turn is None:
                    logger.info("line silent through every re-prompt; ending")
                    silent_close = True
                    await session.say(SILENCE_SIGN_OFF)
                    break
                logger.info(
                    "line quiet for %.0fs; re-asking (%d of %d)",
                    SILENCE_SEC, core.state.silence_prompts, MAX_SILENCE_PROMPTS,
                )
                if turn.text:
                    await session.say(turn.text)

            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        logger.info("call cancelled")
    finally:
        # If we are ending on the clock rather than on the conversation, say so
        # first. Then let whatever is mid-sentence finish playing: hanging up
        # over the top of our own closing line is worse than staying on the
        # line half a second longer. See D-044.
        try:
            if timed_out and not silent_close:
                await session.say(WRAP_UP_LINE)
            await session.drain()
        except Exception:
            logger.warning("could not finish the closing utterance cleanly")

        summary = telemetry.summary()
        # Passed in rather than assigned afterwards: `finish` delivers the
        # outcome to the CRM sink, so anything set after it returns never
        # reaches the record. See D-042.
        outcome = await core.finish(
            client={
                "surface": "web",
                "platform": client_info.get("platform"),
                "browser": client_info.get("browser"),
            },
            latency={
                "p50_ms": summary["p50_ms"],
                "p95_ms": summary["p95_ms"],
                "turns_measured": summary["turns_measured"] or 0,
            },
        )

        # Show the caller what the CRM just received. On a real call this
        # goes nowhere near the customer -- here it is the point of the demo:
        # the conversation and the structured record it produced, on one
        # screen.
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps(
                    {
                        "type": "outcome",
                        "payload": outcome.to_payload(),
                        "guardrail_hits": core.state.guardrail_hits,
                        "latency": telemetry.summary(),
                        "stages": telemetry.stage_breakdown(),
                    },
                    default=str,
                ),
                reliable=True,
                topic="outcome",
            )
        except Exception:
            logger.warning("could not publish the outcome to the caller")

        logger.info("outcome: %s (%s)", outcome.outcome, outcome.captured_by)
        logger.info("latency p50/p95: %s / %s ms", summary["p50_ms"], summary["p95_ms"])
        logger.info("stage medians: %s", telemetry.stage_breakdown())
        if core.state.guardrail_hits:
            logger.warning("guardrail hits: %s", core.state.guardrail_hits)

        # The agent ends its own call. Waiting for the customer to hang up
        # leaves the line open after the outcome is already captured, which is
        # how a 2-minute collections call becomes a 9-minute open-ended
        # conversation about anything they feel like asking.
        #
        # Deleting the room rather than disconnecting just this participant:
        # the caller's browser listens for its own disconnect, so leaving the
        # room alive would end the agent's side while the page still showed
        # "On call". A brief pause first, so the outcome message we just
        # published actually lands before the transport goes away.
        try:
            await asyncio.sleep(0.75)
            await ctx.delete_room()
            logger.info("agent ended the call")
        except Exception:
            logger.warning("could not close the room; the caller may have to hang up")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm)
    )
