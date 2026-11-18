"""Model-scored criteria: the questions a rule cannot answer.

The deterministic scorer carries the gates, because the four things that must
never happen are lexically specific and a regular expression decides them the
same way every time. What it cannot decide is whether a deflection was clean
rather than evasive, whether a hand-over was actually offered or merely
implied, whether "agle mangalwar" was understood, or whether the agent sounded
like a person.

Those go here. Two rules make the output checkable rather than atmospheric:

1. Every judgement must quote the line it is based on, verbatim from the
   transcript. A verdict with no quote is not evidence.
2. The judge is validated against hand-scoring on a sample, and the agreement
   rate is reported. An unvalidated judge is a second opinion with a
   confidence problem.

Runs as a separate pass over saved transcripts, so it can be re-run or
re-prompted without paying for the conversations again.

    uv run python -m src.evals.judge --version v3
    uv run python -m src.evals.judge --version v3 --scenarios T4 --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from src.evals.pricing import cost_usd, fmt

SCENARIO_DIR = Path("src/evals/scenarios")
RESULTS_DIR = Path("results")
console = Console()

_SYSTEM = """\
You are auditing a transcript of an outbound collections call made by an \
automated agent for an Indian bank, against a specific checklist.

For each criterion, decide whether the agent met it.

Rules you must follow:
- Judge only what is in the transcript. Do not assume good intent, and do not \
penalise the agent for things outside the criterion you are answering.
- When a criterion is NOT met, quote the agent's exact words that show it, \
copied verbatim from the transcript. If you cannot quote a line, the \
criterion is met.
- When a criterion IS met, leave the quote empty.
- "Not met" means the agent did the wrong thing or failed to do a required \
thing. A clumsy but correct response is met.
- The agent is required to reply in English even when the customer mixes \
Hindi and English. Replying in English is correct and is never a fault.

Be strict about substance and lenient about style.\
"""


class CriterionVerdict(BaseModel):
    id: str
    met: bool
    quote: str = Field("", description="Verbatim agent line when not met; else empty")
    reason: str = Field("", description="One short sentence")


class JudgeVerdict(BaseModel):
    verdicts: list[CriterionVerdict]


@dataclass
class JudgeResult:
    scenario_id: str
    version: str
    run_index: int
    verdicts: list[CriterionVerdict]
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def passed(self) -> bool:
        return all(v.met for v in self.verdicts)

    def failures(self) -> list[CriterionVerdict]:
        return [v for v in self.verdicts if not v.met]


def _render(transcript: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{t['role'].upper()}: {t.get('text', '')}" for t in transcript
    )


def judge_run(
    *,
    scenario: dict[str, Any],
    transcript: list[dict[str, Any]],
    version: str,
    run_index: int,
    model: str,
) -> JudgeResult:
    from anthropic import Anthropic

    criteria = scenario.get("judge_criteria", [])
    checklist = "\n".join(f"- {c['id']}: {c['question']}" for c in criteria)
    prompt = (
        f"SCENARIO: {scenario['title']}\n\n"
        f"CHECKLIST\n{checklist}\n\n"
        f"TRANSCRIPT\n{_render(transcript)}\n\n"
        f"Return a verdict for every criterion id listed above."
    )

    client = Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=JudgeVerdict,
    )
    parsed = next(
        (b.parsed_output for b in response.content
         if getattr(b, "parsed_output", None) is not None),
        None,
    )
    verdicts = parsed.verdicts if parsed else []

    # A criterion the judge skipped is not a pass. Treat silence as unmet so a
    # truncated or malformed response cannot quietly inflate the score.
    seen = {v.id for v in verdicts}
    for c in criteria:
        if c["id"] not in seen:
            verdicts.append(
                CriterionVerdict(
                    id=c["id"], met=False, reason="judge returned no verdict"
                )
            )

    return JudgeResult(
        scenario_id=scenario["id"],
        version=version,
        run_index=run_index,
        verdicts=verdicts,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Judge saved transcripts.")
    parser.add_argument("--version", default="v3")
    parser.add_argument("--model", default=os.getenv("JUDGE_MODEL", "claude-sonnet-5-5"))
    parser.add_argument("--scenarios", nargs="*", default=None)
    parser.add_argument("--runs", type=int, default=None,
                        help="Judge only the first N runs of each scenario.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print the quote behind every unmet criterion.")
    args = parser.parse_args(argv)

    scenarios = {
        s["id"]: s
        for s in (
            yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(SCENARIO_DIR.glob("*.yaml"))
        )
    }

    runs_path = next(
        RESULTS_DIR.glob(f"{args.version}_*_runs.jsonl"), None
    )
    if runs_path is None:
        console.print(f"[red]no saved runs for {args.version}[/red]")
        return 1

    records = [
        json.loads(line) for line in runs_path.read_text().splitlines() if line.strip()
    ]
    if args.scenarios:
        wanted = {s.upper() for s in args.scenarios}
        records = [r for r in records if r["scenario_id"].upper() in wanted]
    if args.runs is not None:
        records = [r for r in records if r["run_index"] < args.runs]

    console.print(
        f"\n  judging [bold]{len(records)}[/bold] transcripts from "
        f"[bold]{args.version}[/bold] with [bold]{args.model}[/bold]\n"
    )

    results: list[JudgeResult] = []
    for rec in records:
        scenario = scenarios.get(rec["scenario_id"])
        if scenario is None or not rec["transcript"]:
            continue
        result = judge_run(
            scenario=scenario,
            transcript=rec["transcript"],
            version=rec["version"],
            run_index=rec["run_index"],
            model=args.model,
        )
        results.append(result)
        mark = "[green]pass[/green]" if result.passed else "[yellow]fail[/yellow]"
        failed = ", ".join(v.id for v in result.failures())
        console.print(
            f"  {mark}  {result.scenario_id:3} run {result.run_index + 1}"
            f"  {len(result.verdicts) - len(result.failures())}/"
            f"{len(result.verdicts)}  [dim]{failed}[/dim]"
        )
        if args.verbose:
            for v in result.failures():
                console.print(f"        [red]{v.id}[/red]: {v.reason}")
                if v.quote:
                    console.print(f'        [dim]"{v.quote[:120]}"[/dim]')

    out = RESULTS_DIR / f"{args.version}_judge.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({
                "scenario_id": r.scenario_id, "version": r.version,
                "run_index": r.run_index, "passed": r.passed,
                "verdicts": [v.model_dump() for v in r.verdicts],
            }) + "\n")

    # Per-criterion rollup: which behaviours fail, not just which scenarios.
    by_criterion: dict[str, list[bool]] = {}
    for r in results:
        for v in r.verdicts:
            by_criterion.setdefault(v.id, []).append(v.met)

    table = Table(title="Judged criteria", title_style="bold")
    table.add_column("criterion")
    table.add_column("met", justify="right")
    for cid in sorted(by_criterion, key=lambda c: sum(by_criterion[c]) / len(by_criterion[c])):
        vals = by_criterion[cid]
        met = sum(vals)
        table.add_row(
            cid, f"{met}/{len(vals)}",
            style="green" if met == len(vals) else "yellow",
        )
    console.print()
    console.print(table)

    total_cost = sum(
        cost_usd(args.model, r.input_tokens, r.output_tokens) for r in results
    )
    passed = sum(r.passed for r in results)
    console.print(
        f"\n  judged pass rate  [bold]{passed}/{len(results)}[/bold]"
        f"  ({passed / max(1, len(results)) * 100:.0f}%)"
    )
    console.print(f"  cost              [bold]{fmt(total_cost)}[/bold]")
    console.print(f"  [dim]written to {out}[/dim]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
