"""Export the run records to results/eval_results.csv.

One row per conversation, which is the grain a reader can audit: version,
scenario, run, outcome, every gate and metric as pass/fail, the rules it
broke, turns, duration and cost. The summary tables in the writeup are all
derivable from this file, which is the point -- a table nobody can recompute
is an assertion.

    uv run python -m src.evals.export
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = ROOT / "results"
OUT = RESULTS / "eval_results.csv"

GATES = ("G1", "G2", "G3", "G4")
METRICS = ("M1", "M2", "M3", "M4")

FIELDS = [
    "version", "model", "scenario", "run", "bucket",
    "customer_id", "expected_outcome", "actual_outcome", "passed",
    *GATES, *METRICS,
    "gates_held", "gates_checked",
    "violations", "guardrail_hits",
    "customer_turns", "duration_sec", "otp_verified", "waiver_requested",
    "cost_usd", "error",
]


def _checks(record: dict) -> dict[str, str]:
    """Flatten the check list into one column per gate and metric.

    Blank, not "pass", where a check did not apply: G4 only applies to a
    scenario where a hand-over is due, and scoring a call that never had the
    chance to breach it as a pass would inflate every average quietly.
    """
    out: dict[str, str] = {k: "" for k in (*GATES, *METRICS)}
    for check in record.get("checks", []):
        cid = check.get("id", "")
        if cid in out:
            out[cid] = "pass" if check.get("passed") else "FAIL"
    return out


def rows() -> list[dict]:
    collected: list[dict] = []
    for path in sorted(RESULTS.glob("v*_runs.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            o = r.get("outcome") or {}
            checks = _checks(r)
            gates = [c for c in r.get("checks", []) if c.get("kind") == "gate"]
            collected.append({
                "version": r.get("version", path.name.split("_")[0]),
                "model": r.get("model", ""),
                "scenario": r.get("scenario_id", ""),
                "run": r.get("run_index", ""),
                "bucket": r.get("bucket", ""),
                "customer_id": o.get("customer_id", r.get("customer_id", "")),
                "expected_outcome": r.get("expected_outcome", ""),
                "actual_outcome": o.get("outcome", ""),
                "passed": "pass" if r.get("passed") else "FAIL",
                **checks,
                "gates_held": sum(1 for c in gates if c.get("passed")),
                "gates_checked": len(gates),
                "violations": "; ".join(
                    v if isinstance(v, str) else
                    f"{v.get('severity','')}:{v.get('rule_id','')}"
                    for v in (r.get("violations") or [])
                ),
                "guardrail_hits": "; ".join(o.get("guardrail_hits") or []),
                "customer_turns": o.get("turn_count", ""),
                "duration_sec": o.get("duration_sec", ""),
                "otp_verified": o.get("otp_verified", ""),
                "waiver_requested": o.get("waiver_requested", ""),
                "cost_usd": r.get("cost_usd", ""),
                "error": r.get("error") or "",
            })
    return collected


def main() -> None:
    data = rows()
    RESULTS.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    # Keyed by version AND model. Grouping on version alone merged the Haiku
    # and Sonnet runs of v3 into one row of 102 conversations, which is two
    # different systems added together and reported as one number.
    by_version: dict[tuple[str, str], list[dict]] = {}
    for row in data:
        by_version.setdefault((row["version"], row["model"]), []).append(row)

    print(f"  wrote {OUT.relative_to(ROOT)}  ({len(data)} conversations)\n")
    # Two denominators, both reported, because quoting one as "gates held"
    # invites being contradicted by the other. A gate check can pass 70% of
    # the time while only 27% of calls are clean, and for a release decision
    # the per-call figure is the one that matters: any single breach fails it.
    print(f"  {'version · model':30} {'calls passed':>14} {'clean calls':>14}"
          f" {'gate checks':>14}")
    for key in sorted(by_version):
        v = f"{key[0]} · {key[1].replace('claude-', '')}"
        rs = by_version[key]
        passed = sum(1 for r in rs if r["passed"] == "pass")
        clean = sum(1 for r in rs if r["gates_held"] == r["gates_checked"])
        held = sum(r["gates_held"] for r in rs)
        checked = sum(r["gates_checked"] for r in rs)
        print(
            f"  {v:30}"
            f" {f'{passed}/{len(rs)}':>7} {f'{100 * passed / len(rs):.0f}%':>6}"
            f" {f'{clean}/{len(rs)}':>7} {f'{100 * clean / len(rs):.0f}%':>6}"
            f" {f'{held}/{checked}':>8} {f'{100 * held / checked:.0f}%':>5}"
        )
    print(
        "\n  clean calls = calls with no gate breach at all. That is the"
        "\n  release figure: one breach fails a call outright, so an average"
        "\n  over individual checks flatters it."
    )


if __name__ == "__main__":
    main()
