"""Speech recognition accuracy on real Hinglish, scored on entities.

Word error rate is the wrong metric for this product. A transcript that
renders "mangalwar" as "mangal war" costs nothing; one that turns four
thousand five hundred into four thousand puts a wrong commitment in the CRM.
Only three things have to survive transcription on a collections call -- the
amount, the date and the payment rail -- so those are what is scored.

Every clip is transcribed twice: once at 16kHz, and once downsampled to 8kHz
mu-law and back, which approximates a narrowband phone line. The gap between
the two numbers is the honest cost of demonstrating this in a browser rather
than over the telephone network.

    uv run python -m src.evals.voice.stt_harness
    uv run python -m src.evals.voice.stt_harness --show-transcripts
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.core.guardrails.numerics import numbers_spoken
from src.core.policy import STT_KEYTERMS

HERE = Path(__file__).parent
AUDIO_DIR = HERE / "audio"
GROUND_TRUTH = HERE / "ground_truth.yaml"
OUT_CSV = Path("results/stt_accuracy.csv")

console = Console()

#: Tokens that satisfy each date reference, in either language. Matching is
#: deliberately loose -- the agent only has to understand which day was meant,
#: not reproduce the customer's phrasing.
#: Both scripts, because nova-3 returns Hindi in Devanagari and English in
#: Latin, often inside the same sentence.
DATE_TOKENS: dict[str, list[str]] = {
    "next tuesday": ["mangalwar", "mangal war", "tuesday", "मंगलवार"],
    "7th": ["saat", "7", "seven", "saatv", "सात", "७"],
    "last week": ["pichle", "pichhle", "last week", "pichley",
                  "पिछले", "पिछले हफ़्ते", "पिछले हफ्ते"],
    "two days ago": ["do din", "2 din", "two days", "2 days", "दो दिन"],
    "next week": ["agle hafte", "next week", "agle haftey",
                  "अगले हफ़्ते", "अगले हफ्ते"],
    "30th": ["tees", "30", "thirty", "तीस", "३०", "आखिर"],
    "tomorrow": ["kal", "tomorrow", "कल"],
    "friday": ["friday", "shukrawar", "shukravar", "शुक्रवार"],
}

PAYMENT_PATTERNS: dict[str, str] = {
    "NEFT": r"\bn\.?\s?e\.?\s?f\.?\s?t\b|\bneft\b|एनईएफटी",
    "UPI": r"\bu\.?\s?p\.?\s?i\b|\bupi\b|यूपीआई",
    "IMPS": r"\bi\.?\s?m\.?\s?p\.?\s?s\b|\bimps\b|आईएमपीएस",
    "net banking": r"\bnet\s?banking\b|\binternet\s?banking\b|नेट\s?बैंकिंग",
}


@dataclass
class ClipResult:
    clip_id: str
    rate: str
    transcript: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    error: str | None = None

    @property
    def entities(self) -> int:
        return len(self.checks)

    @property
    def correct(self) -> int:
        return sum(self.checks.values())


def _convert(source: Path, rate: str) -> Path:
    """Render a clip at the requested quality.

    `phone` goes through 8kHz mu-law and back, which is what a PSTN leg does
    to audio. Doing it here means the number we report for telephony is
    measured rather than assumed.
    """
    out = Path(tempfile.mkstemp(suffix=".wav")[1])
    if rate == "clean":
        args = ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"]
    else:
        args = ["-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw"]
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), *args, str(out)],
        check=True, capture_output=True,
    )
    return out


def _transcribe(path: Path, api_key: str) -> str:
    params: list[tuple[str, str]] = [
        ("model", "nova-3"),
        ("language", "multi"),
        ("smart_format", "true"),
        ("punctuate", "true"),
    ]
    params += [("keyterm", term) for term in STT_KEYTERMS]

    resp = httpx.post(
        "https://api.deepgram.com/v1/listen",
        params=params,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
        },
        content=path.read_bytes(),
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return (
        data["results"]["channels"][0]["alternatives"][0]["transcript"] or ""
    ).strip()


def _check(expect: dict[str, Any], transcript: str) -> dict[str, bool]:
    """Did the three things that matter survive?"""
    low = transcript.lower()
    checks: dict[str, bool] = {}

    if "amount" in expect:
        checks["amount"] = str(expect["amount"]) in numbers_spoken(transcript)

    if "payment_mode" in expect:
        pattern = PAYMENT_PATTERNS.get(expect["payment_mode"])
        checks["payment_mode"] = bool(pattern and re.search(pattern, low))

    if "date_ref" in expect:
        tokens = DATE_TOKENS.get(expect["date_ref"], [expect["date_ref"]])
        checks["date_ref"] = any(t.lower() in low for t in tokens)

    return checks


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score Hinglish transcription.")
    parser.add_argument("--show-transcripts", action="store_true")
    parser.add_argument("--rates", nargs="*", default=["clean", "phone"])
    args = parser.parse_args(argv)

    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        console.print("[red]DEEPGRAM_API_KEY is not set[/red]")
        return 1

    truth = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))["utterances"]
    results: list[ClipResult] = []

    for rate in args.rates:
        label = "16kHz" if rate == "clean" else "8kHz mu-law (phone)"
        console.print(f"\n  [bold]{label}[/bold]")
        for item in truth:
            matches = list(AUDIO_DIR.glob(f"{item['id']}.*"))
            if not matches:
                console.print(f"    [yellow]{item['id']}: no audio file[/yellow]")
                continue

            result = ClipResult(clip_id=item["id"], rate=rate)
            try:
                wav = _convert(matches[0], rate)
                result.transcript = _transcribe(wav, api_key)
                wav.unlink(missing_ok=True)
                result.checks = _check(item.get("expect") or {}, result.transcript)
            except Exception as exc:  # noqa: BLE001
                result.error = f"{type(exc).__name__}: {exc}"

            results.append(result)

            if result.error:
                mark = "[red]ERR [/red]"
            elif not result.checks:
                mark = "[dim]  - [/dim]"   # nothing to score on this clip
            elif result.correct == result.entities:
                mark = "[green]pass[/green]"
            else:
                mark = "[red]FAIL[/red]"

            detail = ", ".join(
                f"{k}{'' if v else ' MISSED'}" for k, v in result.checks.items()
            )
            console.print(f"    {mark} {result.clip_id}  [dim]{detail}[/dim]")
            if args.show_transcripts:
                console.print(f'         [dim]"{result.transcript}"[/dim]')

    # -- rollup -----------------------------------------------------------
    table = Table(title="Entity accuracy", title_style="bold")
    table.add_column("entity")
    for rate in args.rates:
        table.add_column("16kHz" if rate == "clean" else "8kHz", justify="right")

    entity_types = ["amount", "date_ref", "payment_mode"]
    for entity in entity_types:
        row = [entity]
        for rate in args.rates:
            vals = [
                r.checks[entity] for r in results
                if r.rate == rate and entity in r.checks
            ]
            row.append(f"{sum(vals)}/{len(vals)}" if vals else "-")
        table.add_row(*row)

    row = ["[bold]all entities[/bold]"]
    for rate in args.rates:
        vals = [v for r in results if r.rate == rate for v in r.checks.values()]
        pct = f"{sum(vals) / len(vals) * 100:.0f}%" if vals else "-"
        row.append(f"[bold]{sum(vals)}/{len(vals)} ({pct})[/bold]" if vals else "-")
    table.add_row(*row)

    console.print()
    console.print(table)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["clip_id", "rate", "entity", "expected_met", "transcript"])
        for r in results:
            for entity, ok in r.checks.items():
                writer.writerow([r.clip_id, r.rate, entity, ok, r.transcript])
    console.print(f"\n  [dim]written to {OUT_CSV}[/dim]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
