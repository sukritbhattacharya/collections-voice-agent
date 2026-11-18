"""Verify credentials and connectivity before a run costs anything.

Each check is the cheapest call that proves the key actually works -- an
unauthenticated 401 and a typo in a variable name look identical from the
application, and finding out mid-run is expensive in time rather than money.
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

OK, FAIL, SKIP = "\033[32m  ok  \033[0m", "\033[31m fail \033[0m", "\033[33m skip \033[0m"


def row(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name:<22} {detail}")


def check_anthropic() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        row("Anthropic", SKIP, "ANTHROPIC_API_KEY not set — required")
        return False
    try:
        from anthropic import Anthropic

        client = Anthropic()
        model = os.getenv("AGENT_MODEL", "claude-haiku-5-5")
        resp = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with the word: ok"}],
        )
        used = resp.usage.input_tokens + resp.usage.output_tokens
        row("Anthropic", OK, f"{model} responded, {used} tokens (~$0.000002)")
        return True
    except Exception as exc:  # noqa: BLE001 - surface whatever went wrong
        row("Anthropic", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
        return False


def check_deepgram() -> bool:
    key = os.getenv("DEEPGRAM_API_KEY", "")
    if not key:
        row("Deepgram", SKIP, "not set — only needed for voice mode")
        return True
    try:
        resp = httpx.get(
            "https://api.deepgram.com/v1/projects",
            headers={"Authorization": f"Token {key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            projects = resp.json().get("projects", [])
            name = projects[0]["name"] if projects else "no project"
            row("Deepgram", OK, f"authenticated — {name}")
            return True
        row("Deepgram", FAIL, f"HTTP {resp.status_code} — check the key")
        return False
    except Exception as exc:  # noqa: BLE001
        row("Deepgram", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
        return False


def check_webhook() -> bool:
    url = os.getenv("OUTCOME_WEBHOOK_URL", "")
    if not url:
        row("Outcome webhook", SKIP, "not set — outcomes go to results/ only")
        return True
    try:
        resp = httpx.post(
            url,
            json={"probe": True, "source": "collections-voice-agent setup check"},
            timeout=10.0,
        )
        if resp.status_code < 400:
            row("Outcome webhook", OK, f"accepted a test POST ({resp.status_code})")
            return True
        row("Outcome webhook", FAIL, f"HTTP {resp.status_code}")
        return False
    except Exception as exc:  # noqa: BLE001
        row("Outcome webhook", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
        return False


def check_livekit() -> bool:
    present = [v for v in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
               if os.getenv(v)]
    if not present:
        row("LiveKit", SKIP, "not set — only needed for voice mode")
        return True
    if len(present) < 3:
        row("LiveKit", FAIL, f"only {len(present)}/3 set — all three required")
        return False
    row("LiveKit", OK, os.getenv("LIVEKIT_URL", ""))
    return True


def main() -> int:
    load_dotenv()
    print("\n  Checking configuration\n")
    results = [
        check_anthropic(),
        check_deepgram(),
        check_webhook(),
        check_livekit(),
    ]
    print()
    if results[0]:
        print("  Ready to run evaluations.\n")
        return 0
    print("  Anthropic credentials are required. Add ANTHROPIC_API_KEY to .env\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
