"""Pre-speech check on what the model is about to say.

Everything the brief forbids is checked here, deterministically, before the
words reach text-to-speech. Rules rather than a second model call: the
prohibitions are lexically specific, rules return the same verdict every time,
they cost well under a millisecond against a 1.5s budget, and a compliance
reviewer who does not trust models can read them.

A hit replaces the entire utterance, not the offending span. Surgical redaction
leaves "your credit ___ will be affected", which carries the meaning it was
supposed to remove.

The known weakness is paraphrase -- "this will affect how lenders see you"
names no bureau and passes. That is a documented limitation, and the judge in
the evaluation harness is there partly to catch what these rules miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import yaml

from .numerics import (
    find_bare_numbers,
    find_percentages,
    find_rupee_amounts,
    spell_out_to_digits,
)

RULES_PATH = Path(__file__).parent / "rules.yaml"


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str
    matched_text: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.severity}:{self.rule_id}"


@dataclass
class FilterResult:
    text: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.violations)


@lru_cache(maxsize=1)
def _rules() -> list[dict[str, Any]]:
    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    rules = raw.get("output_rules", [])
    for rule in rules:
        kind = rule.get("kind", "regex")
        if kind == "regex":
            rule["_compiled"] = [
                re.compile(p, re.IGNORECASE) for p in rule["patterns"]
            ]
        elif kind == "numeric_proximity":
            rule["_context"] = [
                re.compile(t, re.IGNORECASE) for t in rule["context_terms"]
            ]
        rule["_replacement"] = " ".join(rule["replacement"].split())
    return rules


#: Words that flip the meaning of a rule hit. "I cannot approve a waiver" is
#: the correct thing to say; a rule that blocks it is a false positive that
#: replaces good output with different good output -- noise in the violation
#: counter, which is a number we report.
_NEGATORS = re.compile(
    r"\b(not|n't|cannot|can't|won't|unable|never|no|afraid|sorry)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW = 30


def _negated(text: str, start: int) -> bool:
    """Whether a negation appears shortly before `start`."""
    return bool(_NEGATORS.search(text[max(0, start - _NEGATION_WINDOW):start]))


def _check_regex(rule: dict[str, Any], text: str) -> Violation | None:
    sensitive = rule.get("negation_sensitive", False)
    for pat in rule["_compiled"]:
        for m in pat.finditer(text):
            if sensitive and _negated(text, m.start()):
                continue
            return Violation(rule["id"], rule["severity"], m.group(0))
    return None


def _check_numeric_proximity(rule: dict[str, Any], text: str) -> Violation | None:
    """Flag a number of the wrong value near a context term.

    Proximity matters: "3.5 percent" is correct and "12 percent interest" is
    not, but a bare "12" elsewhere in the sentence (a date, a card digit) is
    nobody's business. Runs on digit-normalised text so a spelled-out figure
    cannot evade it.
    """
    normalised = spell_out_to_digits(text)
    contexts = [
        m.span() for pat in rule["_context"] for m in pat.finditer(normalised)
    ]
    if not contexts:
        return None

    unit = rule["unit"]
    if unit == "percent":
        candidates = find_percentages(normalised)
    elif unit == "rupees":
        candidates = find_rupee_amounts(normalised)
        if not candidates:
            # No explicit currency marker, so fall back to bare numbers. Guard
            # with min_value: near "late fee", a "2" is a callback window, not
            # a rupee figure.
            floor = int(rule.get("min_value", 0))
            candidates = [
                (v, pos)
                for v, pos in find_bare_numbers(normalised)
                if _as_float(v) is not None and _as_float(v) >= floor
            ]
    else:
        candidates = find_bare_numbers(normalised)

    allowed = {str(v) for v in rule["allowed_values"]}
    window = int(rule.get("window", 60))

    for value, pos in candidates:
        canonical = value.rstrip("0").rstrip(".") if "." in value else value
        if value in allowed or canonical in allowed:
            continue
        for cstart, cend in contexts:
            if min(abs(pos - cend), abs(cstart - pos)) <= window:
                return Violation(
                    rule["id"],
                    rule["severity"],
                    value,
                    detail=f"{value} near '{normalised[cstart:cend]}'",
                )
    return None


def _check_protected_values(
    rule: dict[str, Any], text: str, protected: Sequence[str]
) -> Violation | None:
    """Catch an account figure spoken before verification.

    Checks the raw text and the digit-normalised form, so both "47,500" and
    "forty seven thousand five hundred" are caught.
    """
    if not protected:
        return None
    normalised = spell_out_to_digits(text)
    for value in protected:
        bare = value.replace(",", "")
        for haystack in (text, normalised):
            if re.search(rf"\b{re.escape(value)}\b", haystack) or re.search(
                rf"\b{re.escape(bare)}\b", haystack
            ):
                return Violation(rule["id"], rule["severity"], value)
    return None


def check(
    text: str,
    *,
    protected_values: Sequence[str] = (),
    otp_verified: bool = False,
) -> FilterResult:
    """Inspect a draft utterance.

    `protected_values` holds the account figures that must not be spoken; pass
    an empty sequence once the customer is verified.
    """
    if not text or not text.strip():
        return FilterResult(text=text)

    for rule in _rules():
        kind = rule.get("kind", "regex")

        if kind == "regex":
            hit = _check_regex(rule, text)
        elif kind == "numeric_proximity":
            hit = _check_numeric_proximity(rule, text)
        elif kind == "protected_values":
            if otp_verified:
                continue
            hit = _check_protected_values(rule, text, protected_values)
        else:  # pragma: no cover - guards against a typo in the rules file
            raise ValueError(f"unknown rule kind {kind!r} on {rule['id']}")

        if hit:
            # First hit wins and replaces the whole utterance. Reporting every
            # rule a bad line trips would be noisier without being more useful
            # -- the line is already not being spoken.
            return FilterResult(text=rule["_replacement"], violations=[hit])

    return FilterResult(text=text)
