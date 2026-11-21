"""Repairs to what speech recognition hands us, before the model reads it.

Speech recognition running in a multilingual mode will sometimes return a
*Latin letter* where a customer said a Hindi word. The one that matters on
this call type is "ji" -- the ordinary Hindi affirmative and politeness
particle -- which Nova-3 transcribes as the letter "G".

This is worth being precise about, because the obvious diagnosis is wrong.
Measured against the live model (see D-051):

    "Ji"      -> understood as yes, every time
    "Ji haan" -> understood as yes
    "Haan ji" -> understood as yes
    "G"       -> "Sorry, I didn't catch that clearly."

The model's Hindi is not the problem. It was handed a letter of the English
alphabet and, correctly, had no idea what the customer meant. So the fix
belongs here, at the boundary, and not in the prompt: no amount of instruction
makes "G" mean something, and a prompt that taught the model to read stray
single letters as agreement would be a far worse bargain -- it would start
hearing consent in noise.

Two deliberate limits:

1. **Whole utterance only.** "G" is rewritten when it is the entire turn.
   Inside a longer sentence the surrounding words already carry the meaning
   ("G, Rohan bol raha hoon" was understood correctly without any help), and
   rewriting a letter in the middle of a sentence risks mangling something a
   customer genuinely spelled out.
2. **The transcript keeps the raw text.** The model reads the repair; the
   record shows what recognition actually produced. A transcript that quietly
   reports better input than arrived would hide exactly the failure this
   module exists to measure.
"""

from __future__ import annotations

import re

#: Whole-utterance repairs: what recognition returns -> what was said.
#:
#: Keys are matched case-insensitively with surrounding punctuation stripped,
#: so one entry covers "G", "g", "G." and "G?".
#:
#: Kept deliberately small. Every entry is a transcription artefact observed
#: or expected on a real call, not a translation table -- the model reads
#: Hinglish perfectly well once the words are words.
_WHOLE_UTTERANCE: dict[str, str] = {
    # "ji" -- the live failure this module was written for.
    "g": "Ji",
    "gee": "Ji",
    "jee": "Ji",
    "g g": "Ji ji",
    "g g g": "Ji ji ji",
    # "haan ji" / "ji haan", where only the particle was misheard.
    "haan g": "Haan ji",
    "han g": "Haan ji",
    "g haan": "Ji haan",
    "g han": "Ji haan",
    # "ji nahi" -- a refusal is the costlier one to miss. An unheard "no"
    # keeps a customer on a call they have asked to end.
    "g nahi": "Ji nahi",
    "g nahin": "Ji nahi",
    "nahi g": "Nahi ji",
    "nahin g": "Nahi ji",
}

#: Leading/trailing punctuation and whitespace, stripped before matching.
_EDGES = re.compile(r"^[\s\.\,\!\?\-—–]+|[\s\.\,\!\?\-—–]+$")

#: Internal runs of whitespace, so "g   g" matches "g g".
_RUNS = re.compile(r"\s+")


def repair(text: str) -> tuple[str, str | None]:
    """Return (text_for_the_model, note) for one customer utterance.

    `note` is None when nothing was changed, and otherwise a short
    `raw -> repaired` record for the call's audit trail.
    """
    if not text:
        return text, None

    stripped = _EDGES.sub("", text)
    key = _RUNS.sub(" ", stripped).casefold()
    replacement = _WHOLE_UTTERANCE.get(key)
    if replacement is None or replacement == stripped:
        return text, None
    return replacement, f"{stripped!r} -> {replacement!r}"
