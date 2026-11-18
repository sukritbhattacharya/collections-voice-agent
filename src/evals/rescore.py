"""Re-score saved transcripts without re-running the calls.

The deterministic scorer touches no model, so a change to the rules can be
applied to every conversation already recorded, for free and in under a
second. That matters more than convenience: when a scoring defect is found,
the previously reported numbers can be corrected rather than defended, and
the fix can be shown to have changed only what it should.

    uv run python -m src.evals.rescore
    uv run python -m src.evals.rescore --diff
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.evals.runner import SCENARIO_DIR
from src.evals.scorer import score_run

RESULTS_DIR = Path("results")
console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-score saved runs.")
    parser.add_argument("--diff", action="store_true",
                        help="List runs whose verdict changed.")
    parser.add_argument("--write", action="store_true",
                        help="Overwrite the stored scores in place.")
    args = parser.parse_args(argv)

    scenarios = {
        s["id"]: s
        for s in (
            yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(SCENARIO_DIR.glob("*.yaml"))
        )
    }

    table = Table(title="Re-scored", title_style="bold")
    for col in ("file", "runs", "passed", "gates", "was", "now"):
        table.add_column(col, justify="right" if col != "file" else "left")

    changes: list[str] = []

    for path in sorted(RESULTS_DIR.glob("*_runs.jsonl")):
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if not records:
            continue

        before = sum(r["passed"] for r in records)
        passed = gates = 0
        updated = []

        for rec in records:
            scenario = scenarios.get(rec["scenario_id"])
            if scenario is None:
                continue
            score = score_run(
                scenario=scenario,
                outcome=rec["outcome"],
                transcript=rec["transcript"],
                version=rec["version"],
                model=rec["model"],
                run_index=rec["run_index"],
                error=rec.get("error"),
            )
            passed += score.passed
            gates += score.gates_passed
            if score.passed != rec["passed"]:
                verdict = "pass" if score.passed else "fail"
                changes.append(
                    f"  {rec['version']} {rec['scenario_id']} run {rec['run_index'] + 1}: "
                    f"{'fail' if rec['passed'] is False else 'pass'} -> {verdict}"
                    f"   was: {'; '.join(rec['failures'])[:70]}"
                )
            rec["passed"] = score.passed
            rec["gates_passed"] = score.gates_passed
            rec["failures"] = score.failures()
            updated.append(rec)

        n = len(records)
        table.add_row(
            path.name.replace("_claude-haiku-5-5_runs.jsonl", ""),
            str(n), f"{passed}/{n}", f"{gates}/{n}",
            f"{before / n * 100:.0f}%", f"{passed / n * 100:.0f}%",
        )

        if args.write:
            with path.open("w", encoding="utf-8") as fh:
                for rec in updated:
                    fh.write(json.dumps(rec, default=str) + "\n")

    console.print()
    console.print(table)
    if args.diff and changes:
        console.print("\n  [bold]verdict changes[/bold]")
        for line in changes:
            console.print(line)
    console.print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
