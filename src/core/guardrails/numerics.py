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

#: Hindi number words in Latin script, as customers actually type and say
#: them. The brief says customers reply in a mix of Hindi and English, and
#: amounts are the part that matters -- "chaar hazaar paanch sau" is a figure,
#: and a parser that only reads English silently drops it.
#:
#: Spelling varies wildly in transliteration, so the common variants are all
#: listed rather than normalised. Ambiguity is real: "saat" (7) and "saath"
#: (60) differ by one letter, and speech recognition will sometimes confuse
#: them. That is a known limitation, recorded rather than papered over.
_HINDI_UNITS = {
    "ek": 1, "do": 2, "teen": 3, "theen": 3,
    "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "paach": 5,
    "chhe": 6, "che": 6, "chah": 6, "chhah": 6,
    "saat": 7, "saath": 60, "aath": 8, "ath": 8, "nau": 9,
    "das": 10, "dus": 10, "dash": 10,
    "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19,
    "bees": 20, "bis": 20, "tees": 30, "tis": 30,
    "chalis": 40, "chaalis": 40,
    "pachas": 50, "pachaas": 50, "pachhas": 50,
    "sattar": 70, "assi": 80, "nabbe": 90, "nabbey": 90,
}

#: Hindi number words in Devanagari.
#:
#: This is not a nicety. Deepgram nova-3 with language=multi returns Hindi in
#: Devanagari, not in Latin transliteration -- "chaar hazaar paanch sau" comes
#: back as "चार हज़ार पांच सौ". Every numeric guardrail reads transcripts, so a
#: parser that only knows Latin is blind on live calls, however well it scores
#: against a text simulator.
_DEVANAGARI_UNITS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4,
    "पांच": 5, "पाँच": 5, "छह": 6, "छे": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13,
    "चौदह": 14, "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17,
    "अठारह": 18, "उन्नीस": 19, "बीस": 20, "तीस": 30, "चालीस": 40,
    "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
}

_DEVANAGARI_SCALES = {
    "सौ": 100,
    "हज़ार": 1_000, "हजार": 1_000,
    "लाख": 100_000, "करोड़": 10_000_000, "करोड": 10_000_000,
}

#: Devanagari digits, which smart formatting sometimes emits.
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000,
    "million": 1_000_000,
    # Hindi scale words
    "sau": 100,
    "hazaar": 1_000, "hazar": 1_000, "hajaar": 1_000, "hajar": 1_000,
}
_SCALES.update(_DEVANAGARI_SCALES)

_SKIP = {"and", "a", "-", "aur"}

# Comma-grouped numbers must stay one token. Splitting "10,000" into
# "10" "," "000" invents a bare "000" that later reads as a rupee amount.
_TOKEN_RE = re.compile(r"[A-Za-z]+|[\u0900-\u097F]+|\d[\d,]*(?:\.\d+)?|\S")


_MERGED_UNITS = {**_UNITS, **_HINDI_UNITS, **_DEVANAGARI_UNITS}

#: Hindi scale words are safe in any context; the unit words are not. "do"
#: (two) and "char" (four) are ordinary English words, so reading Hindi
#: numerals out of English text would turn "do you want to pay" into
#: "2 you want to pay".
#:
#: The split is clean because of a rule the agent already follows: it speaks
#: English only. So Hindi parsing is applied to what the CUSTOMER said, and
#: never to what the agent is about to say.
#: Hindi number words in Devanagari.
#:
#: This is not a nicety. Deepgram nova-3 with language=multi returns Hindi in
#: Devanagari, not in Latin transliteration -- "chaar hazaar paanch sau" comes
#: back as "चार हज़ार पांच सौ". Every numeric guardrail reads transcripts, so a
#: parser that only knows Latin is blind on live calls, however well it scores
#: against a text simulator.
_DEVANAGARI_UNITS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4,
    "पांच": 5, "पाँच": 5, "छह": 6, "छे": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13,
    "चौदह": 14, "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17,
    "अठारह": 18, "उन्नीस": 19, "बीस": 20, "तीस": 30, "चालीस": 40,
    "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
}

_DEVANAGARI_SCALES = {
    "सौ": 100,
    "हज़ार": 1_000, "हजार": 1_000,
    "लाख": 100_000, "करोड़": 10_000_000, "करोड": 10_000_000,
}

#: Devanagari digits, which smart formatting sometimes emits.
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

#: Scale words that must not be read out of English text. "sau" and "hazaar"
#: never appear in English, so they are safe to gate; the Devanagari ones are
#: unambiguous by script.
_HINDI_ONLY_SCALES = (
    {"sau", "hazaar", "hazar", "hajaar", "hajar"} | set(_DEVANAGARI_SCALES)
)


def _units_for(include_hindi: bool) -> dict[str, int]:
    return _MERGED_UNITS if include_hindi else _UNITS


def _is_number_word(tok: str, units: dict[str, int]) -> bool:
    low = tok.lower()
    if low in units or low == "point":
        return True
    if low in _SCALES:
        return low not in _HINDI_ONLY_SCALES or units is _MERGED_UNITS
    return False


def spell_out_to_digits(text: str, *, include_hindi: bool = False) -> str:
    """Rewrite spelled-out numbers in `text` as digits.

    Handles "three point five" -> 3.5, "seven hundred and fifty" -> 750,
    "one lakh twenty thousand" -> 120000. Leaves everything else untouched.

    Not a general-purpose parser -- it needs to be good enough that a model
    cannot evade a numeric rule by spelling a figure out, which is a much lower
    bar than parsing arbitrary English.
    """
    units = _units_for(include_hindi)
    text = text.translate(_DEVANAGARI_DIGITS)
    tokens = _TOKEN_RE.findall(text)
    out: list[str] = []
    i = 0

    while i < len(tokens):
        tok = tokens[i]
        if not _is_number_word(tok, units):
            out.append(tok)
            i += 1
            continue

        # Collect a run of number words, allowing "and" inside it.
        start = i
        run: list[str] = []
        while i < len(tokens):
            low = tokens[i].lower()
            if _is_number_word(tokens[i], units):
                run.append(low)
                i += 1
            elif low in _SKIP and run and i + 1 < len(tokens) and _is_number_word(tokens[i + 1], units):
                i += 1  # bridge "hundred and fifty"
            else:
                break

        value = _evaluate(run, units)
        if value is None:
            out.extend(tokens[start:i])
        else:
            out.append(_format(value))

    return " ".join(out)


def _evaluate(words: list[str], units: dict[str, int]) -> float | int | None:
    """Turn a run of number words into a value, or None if it is not one."""
    if not words:
        return None

    # Decimal form: "three point five"
    if "point" in words:
        idx = words.index("point")
        whole_words, frac_words = words[:idx], words[idx + 1:]
        whole = _evaluate_integer(whole_words, units) if whole_words else 0
        if whole is None or not frac_words:
            return None
        digits = "".join(
            str(units[w]) for w in frac_words if w in units and units[w] < 10
        )
        if not digits:
            return None
        return float(f"{whole}.{digits}")

    return _evaluate_integer(words, units)


def _evaluate_integer(words: list[str], units: dict[str, int]) -> int | None:
    total = 0
    current = 0
    seen = False

    for w in words:
        if w in units:
            current += units[w]
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


def numbers_spoken(text: str) -> set[str]:
    """Every number in `text`, as digit strings, spelled-out forms included.

    Used to tell a figure the customer volunteered from one the bank
    disclosed. Both the live filter and the offline scorer call this, so the
    two cannot drift apart on what counts as "the customer said it".
    """
    if not text:
        return set()
    found: set[str] = set()
    text = text.translate(_DEVANAGARI_DIGITS)
    # Hindi numerals included: this reads what the CUSTOMER said.
    for source in (text, spell_out_to_digits(text, include_hindi=True)):
        for value, _ in find_bare_numbers(source):
            found.add(value.replace(",", ""))
    return found
