"""Record the same collections lines in every candidate voice, for listening.

B3 asks whether the agent is intelligible and whether it sounds like someone a
customer would trust. Neither is answerable from a datasheet, and neither shows
up in a text evaluation: a fully compliant agent that sounds wrong for the
market is still the wrong agent.

So the comparison is made the only way it can be -- by listening to the same
sentences, chosen to stress what an Indian collections call actually contains:
a Hindi name, a rupee amount read as words, a date, and a payment rail.

    uv run python -m src.evals.voice.tts_ab

Writes results/voice_ab/<provider>-<voice>-<n>.wav and a manifest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

OUT = Path("results/voice_ab")

LINES = [
    # Name, identity confirmation -- the first thing a customer hears.
    "Hello, this is Priya calling from Mumbai Bank. Am I speaking with Rohan Mehta?",
    # Amount as words, plus a date. The two things that must not be garbled.
    "Your minimum due of four thousand five hundred rupees was payable on the "
    "eighth of November.",
    # A payment rail and a policy figure.
    "If you pay by N E F T or U P I today, it will reflect in two working days. "
    "The late fee is seven hundred and fifty rupees.",
]

DEEPGRAM_VOICES = ["aura-2-thalia-en", "aura-2-asteria-en"]
AZURE_VOICES = ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-IN-AnanyaNeural"]


def deepgram_speak(text: str, voice: str, path: Path) -> None:
    r = httpx.post(
        "https://api.deepgram.com/v1/speak",
        params={"model": voice, "encoding": "linear16", "sample_rate": "24000"},
        headers={
            "Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=60,
    )
    r.raise_for_status()
    path.write_bytes(r.content)


def azure_speak(text: str, voice: str, path: Path) -> None:
    region = os.getenv("AZURE_SPEECH_REGION", "centralindia")
    ssml = (
        f'<speak version="1.0" xml:lang="en-IN">'
        f'<voice name="{voice}">{text}</voice></speak>'
    )
    r = httpx.post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "collections-voice-agent",
        },
        content=ssml.encode(),
        timeout=60,
    )
    r.raise_for_status()
    path.write_bytes(r.content)


def main() -> int:
    load_dotenv()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    jobs = [("deepgram", v, deepgram_speak) for v in DEEPGRAM_VOICES]
    jobs += [("azure", v, azure_speak) for v in AZURE_VOICES]

    for provider, voice, fn in jobs:
        for i, line in enumerate(LINES, start=1):
            path = OUT / f"{provider}-{voice}-{i}.wav"
            try:
                fn(line, voice, path)
                size = path.stat().st_size
                print(f"  ok   {path.name:42} {size // 1024:4} KB")
                manifest.append(
                    {"provider": provider, "voice": voice, "line_no": i,
                     "line": line, "file": str(path), "bytes": size}
                )
            except Exception as exc:
                detail = getattr(getattr(exc, "response", None), "text", "")
                print(f"  FAIL {path.name:42} {type(exc).__name__} {str(exc)[:70]} {detail[:120]}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n{len(manifest)} clips in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
