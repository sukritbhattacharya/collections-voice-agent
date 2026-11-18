"""Runs scenarios against the agent and scores the result.

Drives the same `CollectionsAgent` the voice pipeline uses -- no second copy of
the prompt, no simplified tool layer. If this file talked to a replica, every
number it produced would describe software nobody ships.

    uv run python -m src.evals.runner --version v3 --runs 3
    uv run python -m src.evals.runner --version v1 --scenarios E1 --runs 1
    uv run python -m src.evals.runner --version v3 --model claude-sonnet-5-5
    uv run python -m src.evals.runner --dry-run        # cost estimate only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.core.agent_core import VERSIONS, CollectionsAgent
from src.core.policy import ACCOUNTS
from src.evals.pricing import cost_usd, fmt
from src.evals.scorer import RunScore, score_run
from src.evals.simulator import Simulator

SCENARIO_DIR = Path("src/evals/scenarios")
RESULTS_DIR = Path("results")

#: Rough per-conversation token cost, from measured runs. Only used by
#: --dry-run, so an estimate is honest as long as it is labelled as one.
EST_AGENT_IN, EST_AGENT_OUT = 59_000, 3_500
EST_SIM_IN, EST_SIM_OUT = 18_000, 600

console = Console()


def load_scenarios(only: list[str] | None = None) -> list[dict[str, Any]]:
    scenarios = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(SCENARIO_DIR.glob("*.yaml"))
    ]
    if only:
        wanted = {s.upper() for s in only}
        scenarios = [s for s in scenarios if s["id"].upper() in wanted]
        missing = wanted - {s["id"].upper() for s in scenarios}
        if missing:
            raise SystemExit(f"no such scenario: {', '.join(sorted(missing))}")
    return scenarios


def run_one(
    scenario: dict[str, Any], *, version: str, model: str, run_index: int
) -> tuple[RunScore, dict[str, Any]]:
    """One conversation, end to end."""
    account = ACCOUNTS[scenario["customer_id"]]
    agent = CollectionsAgent(account=account, version=version, model=model)
    simulator = Simulator(persona=scenario["persona"])

    started = time.time()
    error: str | None = None
    try:
        turn = agent.open_call()
        for _ in range(scenario.get("max_turns", 12)):
            said = simulator.reply_to(turn.text)
            if said is None:          # customer hung up
                break
            turn = agent.respond(said)
            if agent.ended:
                break
    except Exception as exc:  # noqa: BLE001 - one bad run must not stop the suite
        error = f"{type(exc).__name__}: {exc}"

    outcome = asyncio.run(agent.finish())
    payload = outcome.model_dump(mode="json")

    agent_cost = cost_usd(
        model,
        getattr(agent.client, "input_tokens", 0),
        getattr(agent.client, "output_tokens", 0),
    )
    sim_cost = cost_usd(
        simulator.model, simulator.input_tokens, simulator.output_tokens
    )

    score = score_run(
        scenario=scenario,
        outcome=payload,
        transcript=outcome.transcript,
        version=version,
        model=model,
        run_index=run_index,
        error=error,
    )

    record = {
        "scenario_id": scenario["id"],
        "scenario_title": scenario["title"],
        "bucket": scenario["bucket"],
        "version": version,
        "model": model,
        "run_index": run_index,
        "passed": score.passed,
        "gates_passed": score.gates_passed,
        "failures": score.failures(),
        "checks": [asdict(c) for c in score.checks],
        "violations": [
            {"rule": v.rule_id, "severity": v.severity, "matched": v.matched_text}
            for v in score.violations
        ],
        "outcome": payload,
        "transcript": outcome.transcript,
        "wall_seconds": round(time.time() - started, 1),
        "cost_usd": round(agent_cost + sim_cost, 6),
        "error": error,
    }
    return score, record


def summarise(scores: list[RunScore], total_cost: float, wall: float) -> None:
    table = Table(title="Results by scenario", title_style="bold")
    table.add_column("id", style="bold")
    table.add_column("runs", justify="right")
    table.add_column("passed", justify="right")
    table.add_column("gates", justify="right")
    table.add_column("failed checks")

    by_scenario: dict[str, list[RunScore]] = {}
    for s in scores:
        by_scenario.setdefault(s.scenario_id, []).append(s)

    for sid in sorted(by_scenario):
        runs = by_scenario[sid]
        passed = sum(r.passed for r in runs)
        gates = sum(r.gates_passed for r in runs)
        reasons = sorted({
            c.id for r in runs for c in r.checks if not c.passed
        })
        style = "green" if passed == len(runs) else (
            "red" if gates < len(runs) else "yellow"
        )
        table.add_row(
            sid, str(len(runs)), f"{passed}/{len(runs)}", f"{gates}/{len(runs)}",
            ", ".join(reasons), style=style,
        )
    console.print(table)

    total = len(scores)
    passed = sum(s.passed for s in scores)
    gate_ok = sum(s.gates_passed for s in scores)
    console.print(
        f"\n  pass rate      [bold]{passed}/{total}[/bold] "
        f"({passed / total * 100:.0f}%)   "
        f"failure rate [bold]{(total - passed) / total * 100:.0f}%[/bold]"
    )
    console.print(
        f"  gates held     [bold]{gate_ok}/{total}[/bold] "
        f"({gate_ok / total * 100:.0f}%)"
    )
    console.print(
        f"  cost           [bold]{fmt(total_cost)}[/bold]  "
        f"({fmt(total_cost / total)}/conversation)"
    )
    console.print(f"  wall clock     {wall / 60:.1f} min\n")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the evaluation suite.")
    parser.add_argument("--version", choices=sorted(VERSIONS), default="v3")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=os.getenv("AGENT_MODEL", "claude-haiku-5-5"))
    parser.add_argument("--scenarios", nargs="*", default=None,
                        help="Scenario ids, e.g. E1 T5. Default: all.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Estimate cost and exit without calling anything.")
    parser.add_argument("--out", default=None, help="Output JSONL path.")
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    total_runs = len(scenarios) * args.runs
    sim_model = os.getenv("SIMULATOR_MODEL", "claude-haiku-5-5")

    estimate = total_runs * (
        cost_usd(args.model, EST_AGENT_IN, EST_AGENT_OUT)
        + cost_usd(sim_model, EST_SIM_IN, EST_SIM_OUT)
    )
    console.print(
        f"\n  [bold]{args.version}[/bold] · agent [bold]{args.model}[/bold] · "
        f"simulator [bold]{sim_model}[/bold]\n"
        f"  {len(scenarios)} scenarios x {args.runs} runs = "
        f"[bold]{total_runs}[/bold] conversations\n"
        f"  estimated cost [bold]{fmt(estimate)}[/bold] "
        f"[dim](excludes the judge)[/dim]\n"
    )
    if args.dry_run:
        return 0
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[bold red]ANTHROPIC_API_KEY is not set.[/bold red]")
        return 1

    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / f"{args.version}_{args.model}_runs.jsonl"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scores: list[RunScore] = []
    total_cost = 0.0
    started = time.time()

    with out_path.open("w", encoding="utf-8") as fh:
        for run_index in range(args.runs):
            for scenario in scenarios:
                score, record = run_one(
                    scenario, version=args.version, model=args.model,
                    run_index=run_index,
                )
                scores.append(score)
                total_cost += record["cost_usd"]
                fh.write(json.dumps(record, default=str) + "\n")
                fh.flush()

                if record["error"]:
                    mark = "[bold red]ERR [/bold red]"
                elif score.passed:
                    mark = "[green]pass[/green]"
                elif not score.gates_passed:
                    mark = "[red]FAIL[/red]"
                else:
                    mark = "[yellow]fail[/yellow]"
                detail = "" if score.passed else f"  [dim]{'; '.join(score.failures())[:72]}[/dim]"
                console.print(
                    f"  {mark}  {scenario['id']:3} run {run_index + 1}  "
                    f"{record['wall_seconds']:5.1f}s  {fmt(record['cost_usd'])}{detail}"
                )

    console.print()
    summarise(scores, total_cost, time.time() - started)
    console.print(f"  [dim]written to {out_path}[/dim]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
