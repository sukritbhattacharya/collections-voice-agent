"""Write three call transcripts to deliverables/transcripts/ as markdown.

One clean, one where the agent broke, one edge case. Selected by scenario and
run rather than by hand, so re-running the suite and re-running this produces
transcripts of the current code rather than a snapshot someone has to
remember to refresh.

    uv run python scripts/export_transcripts.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "transcripts"

WANTED = [
    ("01_clean.md", "v3", "E1", 1,
     "A clean call",
     "The path this exists to serve: the customer forgot, the agent captures "
     "a date and a mode, and closes with a structured outcome. No guardrail "
     "fires, because nothing needed catching.\n\n"
     "Worth noting that one of the other two runs of this same scenario was "
     "not this clean: the model offered the balance before the customer was "
     "verified and the filter stopped it. Same scenario, same prompt, "
     "different run. That is the variance the guardrails exist for."),
    ("02_the_agent_broke.md", "v1", "L2", 0,
     "The call where the agent broke",
     "**v1 — the supplied prompt, unmodified, with no guardrails.** Over one "
     "conversation it invokes the credit score, threatens legal action and "
     "discusses approving a waiver it has no authority to grant. Every one is "
     "a compliance breach, and the call still reads fluently, which is the "
     "point: nothing about the transcript looks broken unless you know the "
     "policy.\n\n"
     "Across 51 v1 conversations the scorer found "
     "**{v1_violations} compliance violations in {v1_violation_calls} of "
     "them**."),
    ("03_caught_before_it_was_spoken.md", "v3", "E3", 1,
     "A breach the customer never heard",
     "**v3, same prompt as v2, with the output filter in front of speech.** "
     "The customer presses for a waiver. The model held the line, held it "
     "again, and then drafted an approval — the filter replaced the sentence "
     "before it reached text-to-speech and logged "
     "`compliance:waiver_or_discount_approval`. The turn below is the "
     "replacement; the marker under it is where the breach was.\n\n"
     "This is what the architecture buys over the prompt alone. In 51 v3 "
     "conversations the model produced a compliance breach on **8 calls** and "
     "the customer heard **none** of them.\n\n"
     "A limitation worth naming: the transcript stores what was *said*, not "
     "the draft that was blocked. For reviewing a call that is the right "
     "choice; for studying the model's failure modes it is not, and keeping "
     "the rejected draft alongside it is on the list."),
]


def load(version: str) -> list[dict]:
    path = ROOT / "results" / f"{version}_claude-haiku-5-5_runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def corpus_facts() -> dict[str, int]:
    """Numbers quoted in the notes, counted rather than typed.

    A figure retyped into prose is a figure that goes stale the next time the
    suite runs -- this one already had: it said 86 when the corrected rules
    made it 83.
    """
    violations = calls = 0
    path = ROOT / "results" / "v1_claude-haiku-5-5_runs.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        found = [
            v for v in (json.loads(line).get("violations") or [])
            if v.get("severity") == "compliance"
        ]
        violations += len(found)
        calls += bool(found)
    return {"v1_violations": violations, "v1_violation_calls": calls}


def render(record: dict, title: str, note: str) -> str:
    o = record.get("outcome") or {}
    lines = [
        f"# {title}", "",
        note, "",
        "| | |", "|---|---|",
        f"| Version | `{record.get('version')}` |",
        f"| Scenario | `{record.get('scenario_id')}` |",
        f"| Account | `{o.get('customer_id')}` |",
        f"| Outcome | `{o.get('outcome')}` |",
        f"| Verified | {o.get('otp_verified')} |",
        f"| Guardrail hits | {', '.join(o.get('guardrail_hits') or []) or 'none'} |",
        f"| Customer turns | {o.get('turn_count')} |",
        "",
        "---", "",
    ]
    for turn in record.get("transcript", []):
        who = "**Agent**" if turn.get("role") == "agent" else "**Customer**"
        body = textwrap.fill(turn.get("text", ""), 78, subsequent_indent="  ")
        lines.append(f"{who}  \n{body}")
        marks = []
        if turn.get("blocked"):
            marks.append(f"guardrail replaced this line: {', '.join(turn['blocked'])}")
        if turn.get("repaired_to"):
            marks.append(f"speech recognition repaired to {turn['repaired_to']!r}")
        if turn.get("after_silence"):
            marks.append("spoken because the line went quiet")
        if marks:
            lines.append("")
            lines.extend(f"> _{m}_" for m in marks)
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    facts = corpus_facts()
    written = 0
    for name, version, scenario, run, title, note in WANTED:
        match = [
            r for r in load(version)
            if r.get("scenario_id") == scenario and r.get("run_index") == run
        ]
        if not match:
            print(f"  skipped {name}: no {version} {scenario} run {run} on disk")
            continue
        (OUT / name).write_text(
            render(match[0], title, note.format(**facts)), encoding="utf-8")
        print(f"  wrote deliverables/transcripts/{name}")
        written += 1
    print(f"\n  {written} of {len(WANTED)} transcripts exported")


if __name__ == "__main__":
    main()
