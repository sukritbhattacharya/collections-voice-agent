"""Spoken-number handling.

The agent is told to speak amounts as words, because text-to-speech reads
"seven hundred and fifty" better than "750". That instruction defeats any
guardrail looking for digits: a model that says "around twelve percent" would
sail past a regex hunting for `12`.

So before the numeric rules run, spelled-out numbers are converted back to
digits. Indian scale words (lakh, crore) are included because this is an Indian
product and a model will reach for them.
"""

from __future__ import annotations

import re

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000,
    "million": 1_000_000,
}

_SKIP = {"and", "a", "-"}

# Comma-grouped numbers must stay one token. Splitting "10,000" into
# "10" "," "000" invents a bare "000" that later reads as a rupee amount.
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d[\d,]*(?:\.\d+)?|\S")


def _is_number_word(tok: str) -> bool:
    low = tok.lower()
    return low in _UNITS or low in _SCALES or low == "point"


def spell_out_to_digits(text: str) -> str:
    """Rewrite spelled-out numbers in `text` as digits.

    Handles "three point five" -> 3.5, "seven hundred and fifty" -> 750,
    "one lakh twenty thousand" -> 120000. Leaves everything else untouched.

    Not a general-purpose parser -- it needs to be good enough that a model
    cannot evade a numeric rule by spelling a figure out, which is a much lower
    bar than parsing arbitrary English.
    """
    tokens = _TOKEN_RE.findall(text)
    out: list[str] = []
    i = 0

    while i < len(tokens):
        tok = tokens[i]
        if not _is_number_word(tok):
            out.append(tok)
            i += 1
            continue

        # Collect a run of number words, allowing "and" inside it.
        start = i
        run: list[str] = []
        while i < len(tokens):
            low = tokens[i].lower()
            if _is_number_word(tokens[i]):
                run.append(low)
                i += 1
            elif low in _SKIP and run and i + 1 < len(tokens) and _is_number_word(tokens[i + 1]):
                i += 1  # bridge "hundred and fifty"
            else:
                break

        value = _evaluate(run)
        if value is None:
            out.extend(tokens[start:i])
        else:
            out.append(_format(value))

    return " ".join(out)


def _evaluate(words: list[str]) -> float | int | None:
    """Turn a run of number words into a value, or None if it is not one."""
    if not words:
        return None

    # Decimal form: "three point five"
    if "point" in words:
        idx = words.index("point")
        whole_words, frac_words = words[:idx], words[idx + 1:]
        whole = _evaluate_integer(whole_words) if whole_words else 0
        if whole is None or not frac_words:
            return None
        digits = "".join(
            str(_UNITS[w]) for w in frac_words if w in _UNITS and _UNITS[w] < 10
        )
        if not digits:
            return None
        return float(f"{whole}.{digits}")

    return _evaluate_integer(words)


def _evaluate_integer(words: list[str]) -> int | None:
    total = 0
    current = 0
    seen = False

    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
            seen = True
        elif w in _SCALES:
            scale = _SCALES[w]
            if current == 0:
                current = 1
            if scale >= 1_000:
                total += current * scale
                current = 0
            else:
                current *= scale
            seen = True
        else:
            return None

    return total + current if seen else None


def _format(value: float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_DIGIT_PERCENT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:%|percent|per\s*cent|pc\b)", re.IGNORECASE
)
_DIGIT_RUPEES = re.compile(
    r"(?:(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?))"
    r"|(?:(\d[\d,]*(?:\.\d+)?)\s*(?:rupees|rupee|rs\b|inr\b))",
    re.IGNORECASE,
)


def find_percentages(text: str) -> list[tuple[str, int]]:
    """Percentages in `text` as (value, position)."""
    return [(m.group(1), m.start()) for m in _DIGIT_PERCENT.finditer(text)]


def find_rupee_amounts(text: str) -> list[tuple[str, int]]:
    """Rupee amounts in `text` as (value without separators, position)."""
    found: list[tuple[str, int]] = []
    for m in _DIGIT_RUPEES.finditer(text):
        raw = m.group(1) or m.group(2)
        found.append((raw.replace(",", ""), m.start()))
    return found


def find_bare_numbers(text: str) -> list[tuple[str, int]]:
    """Every standalone number, for contexts where the unit is implied."""
    return [
        (m.group(0).replace(",", ""), m.start())
        for m in re.finditer(r"\b\d[\d,]*(?:\.\d+)?\b", text)
    ]
