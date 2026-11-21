"""Verify credentials and connectivity before a run costs anything.

Each check is the cheapest call that proves the key actually works -- an
unauthenticated 401 and a typo in a variable name look identical from the
application, and finding out mid-run is expensive in time rather than money.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

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
            # Deliberately not the project name. Deepgram names a default
            # project after the account holder's email address, so printing it
            # puts a personal email on screen -- in a terminal that gets
            # screen-shared, and in any log or screenshot taken of this
            # output. The count proves the key works just as well. See D-063.
            detail = (
                f"authenticated, {len(projects)} project"
                f"{'s' if len(projects) != 1 else ''}"
                if projects else "authenticated, no project found"
            )
            row("Deepgram", OK, detail)
            return True
        row("Deepgram", FAIL, f"HTTP {resp.status_code} — check the key")
        return False
    except Exception as exc:  # noqa: BLE001
        row("Deepgram", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
        return False


WEBHOOK_SITE_FREE_CAP = 50
WEBHOOK_SITE_FREE_DAYS = 7


def _webhook_site_token(url: str) -> str | None:
    """The uuid out of a webhook.site URL, or None if this is some other sink."""
    m = re.search(r"webhook\.site/([0-9a-f-]{36})", url)
    return m.group(1) if m else None


def _webhook_site_headroom(token: str) -> str:
    """How much of the free endpoint is left, and when it dies.

    A free webhook.site URL accepts 50 requests and is then disabled, and the
    URL itself expires a week after it was created. Both are silent: the
    endpoint simply stops being there, and the agent's delivery fails into a
    log line nobody is reading. On a demo that means the CRM pane stays empty
    with no explanation, so the headroom is reported here, before it matters.
    """
    try:
        meta = httpx.get(f"https://webhook.site/token/{token}", timeout=10.0).json()
        used = httpx.get(
            f"https://webhook.site/token/{token}/requests?per_page=1", timeout=10.0
        ).json().get("total", 0)
    except Exception:  # noqa: BLE001
        return ""

    note = f"{used}/{WEBHOOK_SITE_FREE_CAP} requests used"
    created = (meta or {}).get("created_at", "")
    try:
        born = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
        left = (born + timedelta(days=WEBHOOK_SITE_FREE_DAYS) - datetime.now(timezone.utc).replace(tzinfo=None)).days
        note += f", URL expires in {left} day{'s' if left != 1 else ''}"
    except ValueError:
        pass
    return note


def check_webhook() -> bool:
    url = os.getenv("OUTCOME_WEBHOOK_URL", "")
    if not url:
        row("Outcome webhook", SKIP, "not set — outcomes go to results/ only")
        return True

    token = _webhook_site_token(url)
    try:
        resp = httpx.post(
            url,
            json={"probe": True, "source": "collections-voice-agent setup check"},
            timeout=10.0,
        )
        if resp.status_code >= 400:
            row("Outcome webhook", FAIL, f"HTTP {resp.status_code}")
            return False
    except Exception as exc:  # noqa: BLE001
        row("Outcome webhook", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
        return False

    # Delete the probe again. On a 50-request budget, a setup check that
    # spends one of them every time it runs is its own slow leak.
    if token:
        # The POST returns before the request is queryable, so look for it a
        # few times rather than once. The first version checked immediately,
        # found nothing, and silently left the probe behind -- which is the
        # leak this code exists to prevent.
        for _ in range(5):
            try:
                newest = httpx.get(
                    f"https://webhook.site/token/{token}/requests"
                    "?per_page=1&sorting=newest", timeout=10.0,
                ).json().get("data") or []
                if newest and "collections-voice-agent setup check" in str(
                    newest[0].get("content", "")
                ):
                    httpx.delete(
                        f"https://webhook.site/token/{token}"
                        f"/request/{newest[0]['uuid']}",
                        timeout=10.0,
                    )
                    break
            except Exception:  # noqa: BLE001
                break
            time.sleep(0.6)

    detail = f"accepted a test POST ({resp.status_code})"
    if token:
        headroom = _webhook_site_headroom(token)
        if headroom:
            detail += f" — {headroom}"
    row("Outcome webhook", OK, detail)
    return True


def check_azure() -> bool:
    """Confirm the Speech key works and that en-IN voices are reachable.

    Listing voices is the cheapest authenticated call Azure offers, and it
    also proves the region has the Indian voices we chose it for -- a key
    that authenticates in a region without them would pass a naive check and
    fail at call time.
    """
    key = os.getenv("AZURE_SPEECH_KEY", "")
    region = os.getenv("AZURE_SPEECH_REGION", "centralindia")
    if not key:
        row("Azure Speech", SKIP, "not set - only needed for the en-IN voice A/B")
        return True
    try:
        resp = httpx.get(
            f"https://{region}.tts.speech.microsoft.com"
            "/cognitiveservices/voices/list",
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=15.0,
        )
        if resp.status_code == 401:
            row("Azure Speech", FAIL, "key rejected - check KEY 1 and the region")
            return False
        if resp.status_code != 200:
            row("Azure Speech", FAIL, f"HTTP {resp.status_code} from {region}")
            return False
        voices = resp.json()
        indian = [v["ShortName"] for v in voices if v.get("Locale") == "en-IN"]
        wanted = os.getenv("AZURE_TTS_VOICE", "en-IN-NeerjaNeural")
        if wanted not in indian:
            row(
                "Azure Speech", FAIL,
                f"{wanted} not in {region}; available: {', '.join(indian[:3]) or 'none'}",
            )
            return False
        row("Azure Speech", OK, f"{region}, {len(indian)} en-IN voices, {wanted} present")
        return True
    except Exception as exc:  # noqa: BLE001
        row("Azure Speech", FAIL, f"{type(exc).__name__}: {str(exc)[:70]}")
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
        check_azure(),
    ]
    print()
    if results[0]:
        print("  Ready to run evaluations.\n")
        return 0
    print("  Anthropic credentials are required. Add ANTHROPIC_API_KEY to .env\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
