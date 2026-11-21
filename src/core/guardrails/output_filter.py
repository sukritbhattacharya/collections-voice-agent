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
from typing import Any, Mapping, Sequence

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
        if kind in ("regex", "state_regex"):
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

#: Phrases that turn a product mention into a refusal. Saying "for fixed
#: deposit rates, call the helpline" is the behaviour the brief requires; a
#: rule that blocks it is enforcing the opposite of the policy.
_DEFLECTION = re.compile(
    r"(only here for|only able to help with|can(?:'|no)t (?:help|assist|advise|comment|discuss)"
    r"|not able to (?:help|assist|advise|comment|discuss)|please (?:visit|call)"
    r"|helpline|branch|other quer|different team|outside what i)",
    re.IGNORECASE,
)
_DEFLECTION_WINDOW = 120

#: Markers that a wrong figure is being quoted in order to deny it.
#: Matched against digit-normalised text, where the tokeniser separates
#: contractions -- "isn't" arrives as "isn ' t" -- so the apostrophe forms
#: have to tolerate inserted whitespace.
_CORRECTION = re.compile(
    r"(?:\bnot\b|\bnever\b|n\s*'\s*t\b|\brather than\b|\binstead of\b"
    r"|\bno\b|\bactually\b|\bin fact\b)",
    re.IGNORECASE,
)
_CORRECTION_WINDOW = 25


def _near(pattern: re.Pattern[str], text: str, pos: int, window: int) -> bool:
    """Whether `pattern` occurs within `window` characters either side of pos."""
    return bool(pattern.search(text[max(0, pos - window): pos + window]))


def _negated(text: str, start: int) -> bool:
    """Whether a negation appears shortly before `start`."""
    return bool(_NEGATORS.search(text[max(0, start - _NEGATION_WINDOW):start]))


#: Constructions that subordinate the matched phrase to someone else's
#: decision. "Whether the late fee is waived is a decision for a colleague"
#: contains the words of an approval and commits to nothing. Negation alone
#: does not catch these: the refusal is often in the previous sentence,
#: outside the negation window.
_HEDGE_BEFORE = re.compile(
    r"\b(whether|if|depends?\s+on|up\s+to|not\s+(?:my|mine)|decision\s+(?:is|for))\b",
    re.IGNORECASE,
)
_HEDGE_AFTER = re.compile(
    r"^[^.!?]{0,60}?\b(is|are|will\s+be|would\s+be)\s+(a\s+)?"
    r"(decision|matter|call|for\s+(?:a|the|my)\s+colleague|decided|reviewed|"
    r"up\s+to|considered)",
    re.IGNORECASE,
)
_HEDGE_BEFORE_WINDOW = 45


def _hedged(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _HEDGE_BEFORE_WINDOW):start]
    if _HEDGE_BEFORE.search(before):
        return True
    return bool(_HEDGE_AFTER.match(text[end:]))


def _check_regex(rule: dict[str, Any], text: str) -> Violation | None:
    sensitive = rule.get("negation_sensitive", False)
    deflecting = rule.get("deflection_aware", False)
    hedging = rule.get("hedge_sensitive", False)
    for pat in rule["_compiled"]:
        for m in pat.finditer(text):
            if sensitive and _negated(text, m.start()):
                continue
            if deflecting and _near(_DEFLECTION, text, m.start(), _DEFLECTION_WINDOW):
                continue
            if hedging and _hedged(text, m.start(), m.end()):
                continue
            return Violation(rule["id"], rule["severity"], m.group(0))
    return None


def _check_numeric_proximity(
    rule: dict[str, Any],
    text: str,
    account_figures: Sequence[str] = (),
) -> Violation | None:
    """Flag a number of the wrong value *bound to* a context term.

    Binding is by nearest number, not by proximity window. The window alone
    was too loose: in "the minimum payment due is twelve thousand eight
    hundred and forty rupees, and a late fee applies", the minimum due sits
    within sixty characters of "late fee" and was being reported as a wrong
    fee. The fee claim owns the number closest to it; the others belong to
    other claims in the sentence.

    Runs on digit-normalised text so a spelled-out figure cannot evade it.
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

    if not candidates:
        return None

    allowed = {str(v) for v in rule["allowed_values"]}
    # Figures from the customer's own account are not claims about a rate or a
    # fee, whatever they happen to sit next to.
    allowed |= {str(v).replace(",", "") for v in account_figures}
    window = int(rule.get("window", 60))
    correcting = rule.get("correction_aware", False)

    for cstart, cend in contexts:
        # The number this context term is actually talking about: the closest
        # one, in either direction, inside the window.
        def distance(item: tuple[str, int]) -> int:
            pos = item[1]
            return min(abs(pos - cend), abs(cstart - pos))

        nearest = min(candidates, key=distance)
        if distance(nearest) > window:
            continue

        value, pos = nearest
        canonical = value.rstrip("0").rstrip(".") if "." in value else value
        if value in allowed or canonical in allowed:
            continue
        if correcting and _near(_CORRECTION, normalised, pos, _CORRECTION_WINDOW):
            continue

        return Violation(
            rule["id"],
            rule["severity"],
            value,
            detail=f"{value} bound to '{normalised[cstart:cend]}'",
        )
    return None


def _check_protected_values(
    rule: dict[str, Any],
    text: str,
    protected: Sequence[str],
    customer_stated: Sequence[str] = (),
) -> Violation | None:
    """Catch an account figure spoken before verification.

    Checks the raw text and the digit-normalised form, so both "47,500" and
    "forty seven thousand five hundred" are caught.
    """
    if not protected:
        return None
    normalised = spell_out_to_digits(text)
    # A number the customer volunteered is not something the bank disclosed.
    # Confirming "your promise to pay four thousand five hundred" back to
    # someone who just said it is correct call handling, and flagging it as a
    # data breach would be the rule misreading who spoke.
    said_by_customer = {v.replace(",", "") for v in customer_stated}
    for value in protected:
        bare = value.replace(",", "")
        if bare in said_by_customer:
            continue
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
    customer_stated: Sequence[str] = (),
    account_figures: Sequence[str] = (),
    call_flags: Mapping[str, bool] | None = None,
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
            hit = _check_numeric_proximity(rule, text, account_figures)
        elif kind == "protected_values":
            if otp_verified:
                continue
            hit = _check_protected_values(
                rule, text, protected_values, customer_stated
            )
        elif kind == "state_regex":
            # A rule that depends on what this call has established, not only
            # on the words. The pattern alone would be wrong to block: "a
            # colleague will call you back" is the correct thing to say on an
            # account that does carry the fee.
            if not (call_flags or {}).get(rule["requires"]):
                continue
            if otp_verified and not rule.get("forbidden_when_verified", True):
                continue
            hit = _check_regex(rule, text)
        else:  # pragma: no cover - guards against a typo in the rules file
            raise ValueError(f"unknown rule kind {kind!r} on {rule['id']}")

        if hit:
            # First hit wins and replaces the whole utterance. Reporting every
            # rule a bad line trips would be noisier without being more useful
            # -- the line is already not being spoken.
            return FilterResult(text=rule["_replacement"], violations=[hit])

    return FilterResult(text=text)


def scan_all(
    text: str,
    *,
    protected_values: Sequence[str] = (),
    otp_verified: bool = False,
    customer_stated: Sequence[str] = (),
    account_figures: Sequence[str] = (),
    call_flags: Mapping[str, bool] | None = None,
) -> list[Violation]:
    """Report every rule a line breaks, changing nothing.

    `check` stops at the first hit because the line is already being replaced.
    Scoring needs the full picture, and it needs to run over transcripts from
    versions that had no runtime filter at all -- that is how v1 is held to the
    same standard as v3 despite never having been guarded.
    """
    if not text or not text.strip():
        return []

    found: list[Violation] = []
    for rule in _rules():
        kind = rule.get("kind", "regex")
        if kind == "regex":
            hit = _check_regex(rule, text)
        elif kind == "numeric_proximity":
            hit = _check_numeric_proximity(rule, text, account_figures)
        elif kind == "protected_values":
            hit = None if otp_verified else _check_protected_values(
                rule, text, protected_values, customer_stated
            )
        elif kind == "state_regex":
            # Scoring must be able to see this rule too. Returning `continue`
            # here would make a scored transcript silently blind to a whole
            # rule -- the scorer would report a clean call because its
            # instrument never looked. `call_flags` comes off the outcome
            # record, which carries the flag for exactly this purpose.
            if not (call_flags or {}).get(rule["requires"]):
                continue
            if otp_verified and not rule.get("forbidden_when_verified", True):
                continue
            hit = _check_regex(rule, text)
        else:
            continue
        if hit:
            found.append(hit)
    return found
