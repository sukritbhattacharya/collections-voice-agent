"""Text-mode client for the agent.

The same core the voice pipeline drives, reachable from a terminal. Useful for
iterating on the prompt without burning speech credits, and for demonstrating
the agent end to end when audio is unavailable.

    uv run python -m src.core.cli --version v3
    uv run python -m src.core.cli --version v1 --customer MB-9023
    uv run python -m src.core.cli --demo            # scripted, no API key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from .agent_core import VERSIONS, AgentTurn, CollectionsAgent
from .policy import ACCOUNTS, DEFAULT_CUSTOMER_ID

console = Console()


def _in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


DEMO_SCRIPT = [
    ("get_account_context", {}),
    "Good morning, this is Priya calling from Mumbai Bank. "
    "Am I speaking with Rohan Mehta?",
    "Thank you. I'm calling because the minimum payment on your credit card "
    "is overdue. When would you be able to clear it?",
    "I understand. Unfortunately I'm not able to approve a waiver myself, but "
    "I'll note your request and a colleague will call you back about it.",
    ("note_waiver_request", {"what_was_asked": "waive the late fee"}),
    "That's noted. So can I confirm you'll make the payment this Friday?",
    ("log_outcome", {
        "outcome": "PROMISE_TO_PAY",
        "ptp_date": _in_days(3),
        "ptp_amount_inr": 4500,
        "payment_mode": None,
        "paid_on": None,
        "callback_at": None,
        "transfer_reason": None,
        "summary": "Will pay the minimum due on Friday; asked for a fee waiver.",
    }),
    "Thank you, Mr Mehta. I've noted that down. Have a good day.",
]


def _render_turn(turn: AgentTurn, *, show_internals: bool) -> None:
    for event in turn.tool_events:
        if not show_internals:
            continue
        console.print(
            f"  [dim]→ {event.name}("
            f"{', '.join(f'{k}={v!r}' for k, v in event.arguments.items())[:70]})[/dim]"
        )
    if turn.forced_transfer and show_internals:
        console.print(
            f"  [bold yellow]⚠ tripwire: {turn.forced_transfer} "
            f"— hand-over forced[/bold yellow]"
        )
    if turn.violations and show_internals:
        for violation in turn.violations:
            console.print(
                f"  [bold red]⨯ blocked: {violation} — utterance replaced[/bold red]"
            )
    if turn.text:
        console.print(f"[bold cyan]AGENT[/bold cyan]  {turn.text}")
    if show_internals:
        console.print(f"  [dim]{turn.latency_ms} ms[/dim]")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Talk to the collections agent.")
    parser.add_argument("--version", choices=sorted(VERSIONS), default="v3")
    parser.add_argument("--customer", default=DEFAULT_CUSTOMER_ID,
                        choices=sorted(ACCOUNTS))
    parser.add_argument("--model", default=None,
                        help="Overrides AGENT_MODEL.")
    parser.add_argument("--demo", action="store_true",
                        help="Scripted run with no model call. No API key needed.")
    parser.add_argument("--quiet", action="store_true",
                        help="Hide tool calls, guardrail hits and timings.")
    args = parser.parse_args(argv)

    client = None
    if args.demo:
        from .stub_client import StubClient

        client = StubClient(DEMO_SCRIPT)
    elif not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            "[bold red]ANTHROPIC_API_KEY is not set.[/bold red]\n"
            "Copy .env.example to .env and add your key, "
            "or run with --demo for a scripted call that needs no key."
        )
        return 1

    account = ACCOUNTS[args.customer]
    agent = CollectionsAgent(
        account=account, version=args.version, client=client, model=args.model
    )

    console.print(
        Panel(
            f"[bold]{account.name}[/bold] · card ••{account.card_last4} · "
            f"{account.days_past_due} days past due\n"
            f"agent [bold]{args.version}[/bold] · model "
            f"[bold]{agent.model}[/bold]\n"
            f"[dim]Type your replies as the customer. "
            f"Ctrl-D or 'bye' to end the call.[/dim]",
            title="outbound call connecting",
            border_style="blue",
        )
    )

    show = not args.quiet
    _render_turn(agent.open_call(), show_internals=show)

    while not agent.ended:
        try:
            said = console.input("[bold green]YOU[/bold green]    ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not said:
            continue
        if said.lower() in {"bye", "quit", "exit"}:
            break
        _render_turn(agent.respond(said), show_internals=show)

    outcome = asyncio.run(agent.finish())
    console.print()
    console.print(
        Panel(
            Syntax(
                json.dumps(outcome.to_payload(), indent=2),
                "json",
                theme="ansi_dark",
                word_wrap=True,
            ),
            title=f"outcome → CRM  ({outcome.captured_by})",
            border_style="green" if outcome.captured_by == "agent" else "yellow",
        )
    )
    if not os.getenv("OUTCOME_WEBHOOK_URL"):
        console.print(
            "[dim]OUTCOME_WEBHOOK_URL unset — written to "
            "results/outcomes.jsonl only.[/dim]"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
