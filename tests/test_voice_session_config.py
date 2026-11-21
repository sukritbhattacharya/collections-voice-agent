"""The voice session's configuration, checked against the real framework.

Why this file exists. `preemptive_generation=False` was shipped to disable
speculative generation (D-047). It reads correctly, it type-checks, and it
crashes every job at session construction: the option is a nested options
mapping, not a flag. The symptom was an agent that joined the room and never
spoke -- on every device, with 154 passing tests, because not one of them
touched the voice entrypoint. See D-052.

These tests hand the real configuration to the framework's own resolvers.
They need no API key, no room and no audio, and they run in milliseconds.
"""

from __future__ import annotations

import pytest

pytest.importorskip("livekit.agents", reason="voice extra not installed")

from livekit.agents.voice.turn import (  # noqa: E402
    _resolve_endpointing,
    _resolve_preemptive_generation,
)

from src.voice.agent import TURN_HANDLING  # noqa: E402


def test_the_framework_accepts_our_turn_handling_config() -> None:
    """Every key we pass must survive the resolver that reads it.

    This is the assertion whose absence let a crashing session ship.
    """
    for key, resolve in (
        ("preemptive_generation", _resolve_preemptive_generation),
        ("endpointing", _resolve_endpointing),
    ):
        if key in TURN_HANDLING:
            resolve(TURN_HANDLING[key])  # must not raise


def test_speculative_generation_is_off() -> None:
    """The guarantee D-047 rests on.

    The core is stateful: a speculative turn is indistinguishable from a real
    one and corrupts the history. If this is ever flipped back on, barge-in
    breaks again.
    """
    resolved = _resolve_preemptive_generation(
        TURN_HANDLING["preemptive_generation"]
    )
    assert resolved["enabled"] is False


def test_the_option_is_a_mapping_not_a_flag() -> None:
    """Guard the guard: prove the shape that shipped actually fails."""
    with pytest.raises(TypeError):
        _resolve_preemptive_generation(False)  # type: ignore[arg-type]
