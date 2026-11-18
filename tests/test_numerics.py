"""Number parsing, English and Hindi.

The agent speaks amounts as words because that is how text-to-speech should
read them, and customers say amounts in Hindi because that is how they talk.
Every numeric guardrail therefore depends on turning both back into digits --
a rule hunting for "750" sees nothing in "saat sau pachas".
"""

from __future__ import annotations

import pytest

from src.core.guardrails.numerics import (
    find_percentages,
    find_rupee_amounts,
    numbers_spoken,
    spell_out_to_digits,
)

ENGLISH = [
    ("three point five percent", "3.5"),
    ("seven hundred and fifty rupees", "750"),
    ("fifteen hundred", "1500"),
    ("four thousand five hundred", "4500"),
    ("one lakh twenty eight thousand four hundred", "128400"),
    ("twelve percent", "12"),
]

HINDI = [
    ("chaar hazaar paanch sau", "4500"),
    ("do hazaar paanch sau", "2500"),
    ("pachaas hazaar", "50000"),
    ("saat sau pachas", "750"),
    ("ek lakh bees hazaar", "120000"),
    ("das hazaar", "10000"),
]


@pytest.mark.parametrize("phrase,expected", ENGLISH, ids=[p for p, _ in ENGLISH])
def test_english_number_words(phrase: str, expected: str) -> None:
    assert expected in spell_out_to_digits(phrase)


@pytest.mark.parametrize("phrase,expected", HINDI, ids=[p for p, _ in HINDI])
def test_hindi_number_words(phrase: str, expected: str) -> None:
    """Customers reply in Hinglish; the amounts are the part that matters."""
    assert expected in spell_out_to_digits(phrase, include_hindi=True)


def test_hinglish_sentence_keeps_its_non_numeric_words() -> None:
    out = spell_out_to_digits(
        "chaar hazaar paanch sau kar dunga mangalwar ko", include_hindi=True
    )
    assert "4500" in out
    assert "mangalwar" in out


# --- The scoping that makes Hindi parsing safe ----------------------------
#
# "do" (two) and "char" (four) are ordinary English words. Reading Hindi
# numerals out of English would corrupt the agent's own speech, so Hindi is
# applied only to what the customer said -- which is sound because the agent
# replies in English by rule.

ENGLISH_WORDS_THAT_ARE_HINDI_NUMBERS = [
    "Do you want to pay by Friday?",
    "No problem, I will note that down.",
    "Please do call the helpline.",
]


@pytest.mark.parametrize("text", ENGLISH_WORDS_THAT_ARE_HINDI_NUMBERS)
def test_english_agent_speech_is_not_read_as_hindi_numerals(text: str) -> None:
    assert spell_out_to_digits(text) == " ".join(
        __import__("re").findall(r"[A-Za-z]+|\d[\d,]*(?:\.\d+)?|\S", text)
    ), f"English speech was altered by Hindi parsing: {text}"


def test_customer_speech_does_opt_in() -> None:
    assert "2000" in spell_out_to_digits("do hazaar", include_hindi=True)
    assert "2000" not in spell_out_to_digits("do hazaar")


def test_comma_grouped_numbers_survive_intact() -> None:
    """Splitting 10,000 into 10 and 000 invents a figure that was never said."""
    assert "10,000" in spell_out_to_digits("over 10,000 rupees")
    assert find_rupee_amounts(spell_out_to_digits("over 10,000 rupees")) == [
        ("10000", 5)
    ]


def test_numbers_spoken_covers_both_scripts() -> None:
    assert "4500" in numbers_spoken("chaar hazaar paanch sau")
    assert "4500" in numbers_spoken("four thousand five hundred")
    assert "4500" in numbers_spoken("I'll pay 4,500 on Friday")


def test_percentages_need_an_adjacent_number() -> None:
    """"3 and a half percent" is not matched -- and it is also not wrong."""
    assert find_percentages("3.5 percent") == [("3.5", 0)]
    assert find_percentages("3 and a half percent") == []


def test_unparseable_text_is_left_alone() -> None:
    assert spell_out_to_digits("no numbers here at all") == "no numbers here at all"
    assert numbers_spoken("") == set()
