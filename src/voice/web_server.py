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

from src.core.policy import ACCOUNTS, DEFAULT_CUSTOMER_ID, LATE_FEE_THRESHOLD_INR

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

    # Which account this call is about. It travels in the join token as
    # participant metadata, so the agent has it before it speaks -- the
    # greeting names the customer, so this cannot arrive over the data
    # channel after the fact (D-045 is the same mistake made once already).
    #
    # Validated here rather than in the agent: an unknown id would otherwise
    # take the worker's job down with a KeyError mid-demo. See D-053.
    requested = request.query.get("customer") or DEFAULT_CUSTOMER_ID
    if requested not in ACCOUNTS:
        return web.json_response(
            {
                "error": f"unknown customer {requested!r}",
                "known": sorted(ACCOUNTS),
            },
            status=400,
        )

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
        .with_metadata(json.dumps({"customer_id": requested}))
        .with_grants(
            api.VideoGrants(
                room_join=True, room=room,
                can_publish=True, can_subscribe=True,
            )
        )
        .to_jwt()
    )
    return web.json_response(
        {"token": token, "url": url, "room": room, "customer_id": requested}
    )


async def personas(_: web.Request) -> web.Response:
    """The accounts a caller can be. Drives the picker in the client."""
    return web.json_response(
        {
            "default": DEFAULT_CUSTOMER_ID,
            "accounts": [
                {
                    "customer_id": a.customer_id,
                    "name": a.name,
                    "card_last4": a.card_last4,
                    "days_past_due": a.days_past_due,
                    # The demo operator needs to know which account tests
                    # which rule. The late-fee threshold is the interesting
                    # one: two of these four sit either side of it.
                    "late_fee_applies": a.outstanding_inr > LATE_FEE_THRESHOLD_INR,
                }
                for a in ACCOUNTS.values()
            ],
        }
    )


@web.middleware
async def no_store(request: web.Request, handler):
    """Tell every client not to cache anything this server serves.

    aiohttp sends ``Last-Modified`` and ``ETag`` but no ``Cache-Control``.
    With no explicit freshness, a browser is free to apply its own heuristic
    -- typically a fraction of the time since the file was last modified --
    and Safari does. The visible symptom was a phone showing a page without
    the account picker while the server was serving one with it: the handset
    never asked. Nothing here is worth caching (the client is a few KB over a
    local tunnel), and a stale asset during a demo is expensive, so the whole
    surface is marked no-store. See D-057.
    """
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def dashboard(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "dashboard.html")


def _read_outcomes(
    limit: int = 50, *, surface: str | None = None
) -> list[dict]:
    """Recent outcomes, newest first, optionally of one surface only.

    The surface filter is applied *before* the limit, which is the whole point
    of it being an argument rather than something the caller does afterwards.
    Taking the last N records and filtering them gave an empty dashboard
    whenever an evaluation run had appended more than N conversations since
    the last real call -- seven live calls were sitting in the file, invisible,
    because 202 simulated ones came after them. See D-055.
    """
    if not OUTCOMES_LOG.exists():
        return []
    rows: list[dict] = []
    for line in OUTCOMES_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if surface and (row.get("client") or {}).get("surface") != surface:
            continue
        rows.append(row)
    return rows[-limit:][::-1]


async def list_outcomes(request: web.Request) -> web.Response:
    """Recent calls, newest first. Voice calls only by default.

    Evaluation runs write to the same file, and a dashboard showing 150
    simulated conversations alongside three real ones buries the thing you
    are demonstrating.
    """
    limit = int(request.query.get("limit", "50"))
    wanted = request.query.get("surface", "web")
    rows = _read_outcomes(limit, surface=None if wanted == "all" else wanted)
    return web.json_response(rows)


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

    # Only voice calls are streamed, so only voice calls are remembered. The
    # window has to be of the rows we care about: reading the last N records
    # of a file that evaluation runs also append to meant a real call could
    # be pushed out of the window before the next poll and never sent at all.
    # See D-055.
    seen = {r.get("call_id") for r in _read_outcomes(500, surface="web")}
    try:
        while True:
            await asyncio.sleep(1.5)
            for row in reversed(_read_outcomes(50, surface="web")):
                if row.get("call_id") in seen:
                    continue
                seen.add(row.get("call_id"))
                await response.write(
                    f"data: {json.dumps(row, default=str)}\n\n".encode()
                )
            await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return response


def build_app() -> web.Application:
    app = web.Application(middlewares=[no_store])
    app.router.add_get("/", index)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_get("/token", issue_token)
    app.router.add_get("/api/personas", personas)
    app.router.add_get("/api/outcomes", list_outcomes)
    app.router.add_get("/api/stream", stream_outcomes)
    app.router.add_static("/", WEB_DIR, show_index=False)
    return app


if __name__ == "__main__":
    print(f"\n  caller:     http://localhost:{PORT}")
    print(f"  dashboard:  http://localhost:{PORT}/dashboard")
    print(f"  on a phone: ./scripts/tunnel.sh\n")
    web.run_app(build_app(), port=PORT, print=None)
