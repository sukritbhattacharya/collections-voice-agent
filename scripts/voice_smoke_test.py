"""Prove the audio path works, without a microphone.

Joins a room as a headless participant and waits for the agent to be
dispatched, connect, and start speaking. Confirms the parts that cannot be
checked from a unit test:

    worker dispatch -> agent joins -> opening turn generated
      -> text-to-speech produces audio -> frames arrive at the caller

It does not speak back, so it proves the outbound half of the call. The
inbound half (transcription, turn detection) needs a real voice and is
checked by hand.

    uv run python scripts/voice_smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

from dotenv import load_dotenv
from livekit import api, rtc

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID  # noqa: E402

load_dotenv()

TIMEOUT_S = 45


async def main() -> int:
    # Optional: which account to call, e.g.
    #   uv run python scripts/voice_smoke_test.py MB-9023
    customer = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUSTOMER_ID
    if customer not in ACCOUNTS:
        print(f"  unknown customer {customer!r}; known: {', '.join(sorted(ACCOUNTS))}")
        return 1
    print(f"  calling as {ACCOUNTS[customer].name} ({customer})")

    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        print("  LIVEKIT_* not configured")
        return 1

    room_name = f"smoke-{uuid.uuid4().hex[:8]}"
    token = (
        api.AccessToken(key, secret)
        .with_identity("smoke-test-caller")
        # Mirrors what the web client sends, so this also proves the account
        # selection path the live demo depends on. See D-053.
        .with_metadata(json.dumps({"customer_id": customer}))
        .with_name("Smoke Test")
        .with_grants(api.VideoGrants(room_join=True, room=room_name,
                                     can_publish=True, can_subscribe=True))
        .to_jwt()
    )

    room = rtc.Room()
    state = {
        "agent_joined": None,
        "track_subscribed": None,
        "first_frame": None,
        "frames": 0,
        "bytes": 0,
    }
    started = time.perf_counter()

    def elapsed() -> float:
        return round(time.perf_counter() - started, 2)

    @room.on("participant_connected")
    def _joined(p: rtc.RemoteParticipant) -> None:
        if state["agent_joined"] is None:
            state["agent_joined"] = elapsed()
            print(f"  [{state['agent_joined']:>5.2f}s] agent joined: {p.identity}")

    @room.on("track_subscribed")
    def _subscribed(track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        state["track_subscribed"] = elapsed()
        print(f"  [{state['track_subscribed']:>5.2f}s] audio track subscribed")
        asyncio.create_task(_consume(rtc.AudioStream(track)))

    async def _consume(stream: rtc.AudioStream) -> None:
        async for event in stream:
            frame = event.frame
            # Silence is published before speech starts; count only audible
            # frames, or the test passes on an empty track.
            if any(b != 0 for b in bytes(frame.data)[:64]):
                if state["first_frame"] is None:
                    state["first_frame"] = elapsed()
                    print(f"  [{state['first_frame']:>5.2f}s] first audible frame")
                state["frames"] += 1
                state["bytes"] += len(frame.data)

    print(f"\n  room: {room_name}")
    print(f"  connecting as a caller and waiting up to {TIMEOUT_S}s ...\n")
    await room.connect(url, token)
    print(f"  [{elapsed():>5.2f}s] caller connected")

    deadline = time.perf_counter() + TIMEOUT_S
    while time.perf_counter() < deadline:
        if state["frames"] > 50:      # roughly half a second of speech
            break
        await asyncio.sleep(0.25)

    await room.disconnect()

    print()
    checks = [
        ("agent dispatched and joined", state["agent_joined"] is not None),
        ("published an audio track", state["track_subscribed"] is not None),
        ("spoke audible audio", state["first_frame"] is not None),
    ]
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    if state["first_frame"] is not None:
        print(f"\n  time to first audio: {state['first_frame']:.2f}s")
        print(f"  frames received:     {state['frames']} ({state['bytes']:,} bytes)")

    ok = all(c[1] for c in checks)
    print(f"\n  {'voice path works end to end' if ok else 'voice path is broken'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
