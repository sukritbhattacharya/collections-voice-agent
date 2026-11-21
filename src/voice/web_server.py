"""Serves the call client and mints LiveKit tokens.

Small on purpose. The browser needs a signed token to join a room, and a
token endpoint is the smallest thing that can issue one. Everything else here
is static file serving.

    uv run python -m src.voice.web_server            # http://localhost:8080
    ./scripts/tunnel.sh                              # same, over HTTPS, for a phone

Microphone access requires a secure context. localhost counts; a LAN address
does not, which is why a phone needs the tunnel rather than the laptop's IP.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

WEB_DIR = Path(__file__).parent / "web"
PORT = int(os.getenv("WEB_PORT", "8080"))

#: The agent appends every completed call here. The dashboard reads the same
#: file rather than being pushed to separately -- one record of what happened,
#: not two that can disagree.
OUTCOMES_LOG = Path("results/outcomes.jsonl")


async def issue_token(request: web.Request) -> web.Response:
    """A join token for one caller, scoped to one room.

    Tokens are short-lived and single-room. This is a local demo server, so
    it issues one to anybody who asks -- which is fine over an ephemeral
    tunnel and would not be fine in production, where the dialler decides who
    is called rather than the handset.
    """
    room = request.query.get("room") or f"collections-{uuid.uuid4().hex[:8]}"
    identity = request.query.get("identity") or f"customer-{uuid.uuid4().hex[:6]}"

    key, secret = os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")
    url = os.getenv("LIVEKIT_URL")
    if not (key and secret and url):
        return web.json_response(
            {"error": "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set"},
            status=500,
        )

    token = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name("Customer")
        .with_grants(
            api.VideoGrants(
                room_join=True, room=room,
                can_publish=True, can_subscribe=True,
            )
        )
        .to_jwt()
    )
    return web.json_response({"token": token, "url": url, "room": room})


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def dashboard(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "dashboard.html")


def _read_outcomes(limit: int = 50) -> list[dict]:
    if not OUTCOMES_LOG.exists():
        return []
    rows = []
    for line in OUTCOMES_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:][::-1]


async def list_outcomes(request: web.Request) -> web.Response:
    """Recent calls, newest first. Voice calls only by default.

    Evaluation runs write to the same file, and a dashboard showing 150
    simulated conversations alongside three real ones buries the thing you
    are demonstrating.
    """
    limit = int(request.query.get("limit", "50"))
    rows = _read_outcomes(limit * 4)
    if request.query.get("surface", "web") == "web":
        rows = [r for r in rows if (r.get("client") or {}).get("surface") == "web"]
    return web.json_response(rows[:limit])


async def stream_outcomes(request: web.Request) -> web.StreamResponse:
    """Server-sent events, so a completed call appears without a refresh.

    Polls the file rather than coordinating with the agent process. The agent
    may be restarted, run several workers, or be replaced by a hosted
    deployment; the file is the contract between them.
    """
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
    await response.prepare(request)

    seen = {r.get("call_id") for r in _read_outcomes(500)}
    try:
        while True:
            await asyncio.sleep(1.5)
            for row in reversed(_read_outcomes(50)):
                if row.get("call_id") in seen:
                    continue
                seen.add(row.get("call_id"))
                if (row.get("client") or {}).get("surface") != "web":
                    continue
                await response.write(
                    f"data: {json.dumps(row, default=str)}\n\n".encode()
                )
            await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return response


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_get("/token", issue_token)
    app.router.add_get("/api/outcomes", list_outcomes)
    app.router.add_get("/api/stream", stream_outcomes)
    app.router.add_static("/", WEB_DIR, show_index=False)
    return app


if __name__ == "__main__":
    print(f"\n  caller:     http://localhost:{PORT}")
    print(f"  dashboard:  http://localhost:{PORT}/dashboard")
    print(f"  on a phone: ./scripts/tunnel.sh\n")
    web.run_app(build_app(), port=PORT, print=None)
