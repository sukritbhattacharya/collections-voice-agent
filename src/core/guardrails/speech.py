"""Make identifiers speakable before they reach text-to-speech.

A card's last four digits, a one-time password and a helpline number are
**sequences of digits**, not quantities. Read with place value they come out
wrong: `8842` becomes "eighty-eight forty-two" and `1800-123-4567` becomes
"one thousand eight hundred, one hundred twenty-three, four thousand five
hundred sixty-seven". Neither is usable on a phone call, and the second is
actively unhelpful -- a customer cannot write that down.

Measured across every transcript on disk: the agent emitted a raw four-digit
card number 126 times and spelled it out 132 times. A coin flip. The prompt
asks for numbers as words and the model complies about half the time, which is
what an instruction buys. The helpline appeared raw 165 times out of 165.

So this is done deterministically, after the output filter and before speech,
and it is deliberately narrow:

  * amounts are left alone. "750" read with place value is "seven hundred and
    fifty", which is correct, and spelling it digit by digit would be wrong.
    Quantities want place value; identifiers do not.
  * only a known identifier, a phone-shaped run, or a run introduced by a word
    like "ending" or "code" is rewritten.

Runs after the filter, never before: the filter matches this account's
protected figures as digit strings, and rewriting digits into words first
would give an amount a way past it.

See D-062.
"""

from __future__ import annotations

import re

_DIGITS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}

#: Words that introduce an identifier rather than a quantity. "ending in 8842",
#: "code 4471", "account number 2214".
_LEAD = re.compile(
    r"(?:ending(?:\s+(?:in|with))?|card|account|reference|ref|code|password|"
    r"otp|pin|number|digits|helpline|call(?:\s+us)?(?:\s+on)?|dial)"
    r"[\s:,]*(?:is\s+)?$",
    re.IGNORECASE,
)

#: A run of digits, possibly grouped by separators a phone number would use.
_RUN = re.compile(r"\d(?:[\d\-–— ]*\d)?")


def _spell(run: str) -> str:
    """Digit by digit, keeping group boundaries as comma pauses.

    The commas matter: text-to-speech gives them a short pause, which is what
    makes a long number possible to write down while hearing it.
    """
    groups = [g for g in re.split(r"[\-–— ]+", run) if g]
    spoken = [" ".join(_DIGITS[d] for d in g if d.isdigit()) for g in groups]
    return ", ".join(part for part in spoken if part)


def _is_phone_shaped(run: str) -> bool:
    digits = [c for c in run if c.isdigit()]
    if len(digits) >= 7:
        return True
    # Grouped runs like "123-4567" or "4 4 7 1" are being read out, not counted.
    return bool(re.search(r"\d[\-–— ]\d", run)) and len(digits) >= 4


_WORDS = "|".join(_DIGITS.values())
#: Digit words the model has separated with full stops -- "five. five. two.
#: nine." Speech gives a full stop a sentence-length pause, so a card number
#: written that way is read out with gaps that sound like hesitation. Only a
#: stop *between* two digit words is collapsed; the one ending the sentence
#: stays.
_DOTTED = re.compile(rf"\b({_WORDS})\.(?=\s+(?:{_WORDS})\b)", re.IGNORECASE)


def _collapse_dotted(text: str) -> str:
    out = text
    for _ in range(8):  # a four-digit run needs three passes; eight is slack
        nxt = _DOTTED.sub(r"\1", out)
        if nxt == out:
            return out
        out = nxt
    return out


def verbalise(text: str, identifiers: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Rewrite identifier digit runs as spoken digits.

    `identifiers` are this call's own known sequences -- the card's last four,
    the verification code, the helpline. They are rewritten wherever they
    appear, with or without an introducing word, because a bare "8842" in a
    sentence is still a card number.

    Returns the rewritten text and a note per rewrite, for the transcript.
    """
    if not text:
        return text, []

    wanted = {re.sub(r"\D", "", i) for i in identifiers}
    wanted.discard("")
    notes: list[str] = []

    def replace(m: re.Match[str]) -> str:
        run = m.group(0)
        bare = re.sub(r"\D", "", run)
        if not bare:
            return run
        lead = _LEAD.search(text[: m.start()])
        if not (bare in wanted or _is_phone_shaped(run) or lead):
            return run  # a quantity; place value is right for it
        spoken = _spell(run)
        if not spoken or spoken == run:
            return run
        notes.append(f"{run!r} -> {spoken!r}")
        return spoken

    spoken = _RUN.sub(replace, text)
    tidied = _collapse_dotted(spoken)
    if tidied != spoken:
        notes.append("collapsed full stops between spoken digits")
    return tidied, notes
