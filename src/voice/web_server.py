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

import os
import uuid
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

WEB_DIR = Path(__file__).parent / "web"
PORT = int(os.getenv("WEB_PORT", "8080"))


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


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/token", issue_token)
    app.router.add_static("/", WEB_DIR, show_index=False)
    return app


if __name__ == "__main__":
    print(f"\n  call client:  http://localhost:{PORT}")
    print(f"  for a phone:  ./scripts/tunnel.sh\n")
    web.run_app(build_app(), port=PORT, print=None)
