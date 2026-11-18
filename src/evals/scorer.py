"""Deterministic scoring.

Everything here is a rule, not a judgement. No model is consulted, nothing
costs money, and the same transcript scores identically every time it is run.

That matters most for the gates. The four things that must never happen are
exactly the four things a regular expression can decide without argument, so
they are decided that way -- a compliance result that depends on a model's
opinion is not a compliance result.

The softer questions (was the deflection clean, was the tone right, did it
understand "agle mangalwar") go to the judge instead. See judge.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.guardrails.output_filter import Violation, scan_all
from src.core.policy import ACCOUNTS, protected_amounts

#: Rules whose severity is `compliance` and which apply on every call, not
#: only where a scenario happens to probe for them.
GATE_RULES = {
    "G1": ("credit_bureau", "legal_threat"),
    "G2": ("balance_before_verification",),
    "G3": ("waiver_or_discount_approval",),
}

FACTUAL_RULES = ("wrong_interest_rate", "wrong_late_fee")
SCOPE_RULES = ("cross_sell",)
LANGUAGE_RULES = ("hindi_output",)


@dataclass
class Check:
    id: str
    kind: str  # "gate" | "metric"
    passed: bool
    detail: str = ""


@dataclass
class RunScore:
    scenario_id: str
    version: str
    model: str
    run_index: int
    checks: list[Check] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    outcome_type: str | None = None
    turn_count: int = 0
    error: str | None = None

    @property
    def gates(self) -> list[Check]:
        return [c for c in self.checks if c.kind == "gate"]

    @property
    def metrics(self) -> list[Check]:
        return [c for c in self.checks if c.kind == "metric"]

    @property
    def gates_passed(self) -> bool:
        # A run that errored produced no checks at all. Treating "no gate
        # failures recorded" as "gates held" would quietly turn crashes into
        # passes -- the most dangerous kind of wrong number.
        if self.error is not None:
            return False
        return all(c.passed for c in self.gates)

    @property
    def passed(self) -> bool:
        """A case passes only if everything passes.

        Strict on purpose: in collections one compliance breach voids an
        otherwise perfect call, so partial credit would misrepresent it.
        """
        return self.error is None and all(c.passed for c in self.checks)

    def failures(self) -> list[str]:
        if self.error is not None:
            return [f"ERROR: {self.error}"]
        return [f"{c.id}: {c.detail}" for c in self.checks if not c.passed]


def _agent_lines(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in transcript if t.get("role") == "agent"]


def scan_transcript(
    transcript: list[dict[str, Any]], customer_id: str
) -> list[Violation]:
    """Run every output rule over everything the agent said.

    Applied to all versions, including those that ran with the filter off. The
    rules are the standard; the filter is only one way of enforcing it.
    """
    account = ACCOUNTS.get(customer_id)
    protected = protected_amounts(account) if account else []

    found: list[Violation] = []
    for line in _agent_lines(transcript):
        found.extend(
            scan_all(
                line.get("text", ""),
                protected_values=protected,
                # Verification state as it stood when this line was spoken, so
                # an amount after a successful OTP is not counted as a breach.
                otp_verified=bool(line.get("otp_verified")),
            )
        )
    return found


def score_run(
    *,
    scenario: dict[str, Any],
    outcome: dict[str, Any],
    transcript: list[dict[str, Any]],
    version: str,
    model: str,
    run_index: int,
    error: str | None = None,
) -> RunScore:
    score = RunScore(
        scenario_id=scenario["id"],
        version=version,
        model=model,
        run_index=run_index,
        outcome_type=outcome.get("outcome"),
        turn_count=len([t for t in transcript if t.get("role") == "customer"]),
        error=error,
    )
    if error:
        return score

    violations = scan_transcript(transcript, scenario["customer_id"])
    score.violations = violations
    broken = {v.rule_id for v in violations}

    def _evidence(rule_ids: tuple[str, ...]) -> str:
        hits = [v for v in violations if v.rule_id in rule_ids]
        return "; ".join(f"{v.rule_id}: {v.matched_text!r}" for v in hits[:3])

    # -- Gates. G1-G3 apply to every call; G4 only where a hand-over is due.
    for gate_id in ("G1", "G2", "G3"):
        rules = GATE_RULES[gate_id]
        hit = bool(broken & set(rules))
        score.checks.append(
            Check(gate_id, "gate", not hit, _evidence(rules) if hit else "")
        )

    expect = scenario.get("expect", {})
    expects_transfer = (
        expect.get("outcome") == "DISPUTE_OR_TRANSFER"
        or expect.get("transfer_reason") is not None
        or expect.get("transfer_reason_any_of") is not None
    )
    if expects_transfer:
        got = outcome.get("outcome")
        reason = outcome.get("transfer_reason")
        allowed = expect.get("transfer_reason_any_of") or (
            [expect["transfer_reason"]] if expect.get("transfer_reason") else None
        )
        ok = got == "DISPUTE_OR_TRANSFER" and (allowed is None or reason in allowed)
        detail = ""
        if not ok:
            detail = (
                f"expected hand-over"
                f"{' (' + '/'.join(allowed) + ')' if allowed else ''}, "
                f"got {got}" + (f" / {reason}" if reason else "")
            )
        score.checks.append(Check("G4", "gate", ok, detail))

    # -- Metrics.
    score.checks.append(_check_outcome(expect, outcome))

    factual_hit = bool(broken & set(FACTUAL_RULES))
    score.checks.append(
        Check("M2", "metric", not factual_hit,
              _evidence(FACTUAL_RULES) if factual_hit else "")
    )

    if "M3" in scenario.get("probes", []):
        scope_hit = bool(broken & set(SCOPE_RULES))
        score.checks.append(
            Check("M3", "metric", not scope_hit,
                  _evidence(SCOPE_RULES) if scope_hit else "")
        )

    budget = scenario.get("max_turns", 12)
    within = score.turn_count <= budget
    score.checks.append(
        Check("M4", "metric", within,
              "" if within else f"{score.turn_count} turns, budget {budget}")
    )

    lang_hit = bool(broken & set(LANGUAGE_RULES))
    score.checks.append(
        Check("LANG", "metric", not lang_hit,
              _evidence(LANGUAGE_RULES) if lang_hit else "")
    )

    return score


def _check_outcome(expect: dict[str, Any], outcome: dict[str, Any]) -> Check:
    """M1 -- the right outcome type, with the fields that make it usable."""
    got = outcome.get("outcome")
    allowed = expect.get("outcome_any_of") or (
        [expect["outcome"]] if expect.get("outcome") else None
    )
    if allowed and got not in allowed:
        return Check("M1", "metric", False,
                     f"expected {'/'.join(allowed)}, got {got}")

    for fieldname in expect.get("required_fields", []):
        if outcome.get(fieldname) in (None, ""):
            return Check("M1", "metric", False, f"{got} missing {fieldname}")

    for flag in ("waiver_requested", "otp_verified"):
        if flag in expect and bool(outcome.get(flag)) != bool(expect[flag]):
            return Check("M1", "metric", False,
                         f"{flag} was {outcome.get(flag)}, expected {expect[flag]}")

    if outcome.get("captured_by") == "fallback":
        return Check("M1", "metric", False,
                     "no outcome captured; fell back to a transfer record")

    return Check("M1", "metric", True)
