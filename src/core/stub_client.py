"""A scripted stand-in for the model.

Exists so the conversation loop -- tool dispatch, guardrail integration,
outcome capture, transcript assembly -- can be exercised without a network
call or an API key. It is a test fixture, never a fallback: nothing in the
voice path or the evaluation harness may reach for it.

Useful beyond convenience. A scripted "model" that deliberately says forbidden
things proves the output filter fires inside the real loop, not just in a unit
test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    name: str
    input: dict[str, Any]
    id: str = "stub_tool_1"
    type: str = "tool_use"


@dataclass
class _Response:
    content: list[Any]


class StubClient:
    """Replays a fixed script of turns.

    Each scripted turn is either a string (the agent speaks) or a
    ``(tool_name, arguments)`` tuple (the agent calls a tool). Tool turns are
    followed by whatever comes next in the script.
    """

    def __init__(self, script: list[Any], model: str = "stub") -> None:
        self._script: Iterator[Any] = iter(script)
        self.model = model
        self.calls = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> _Response:
        self.calls += 1
        try:
            step = next(self._script)
        except StopIteration:
            return _Response(content=[_Text("Thank you for your time. Goodbye.")])

        if isinstance(step, tuple):
            name, arguments = step
            allowed = {t["name"] for t in tools}
            if name not in allowed:
                # Mirrors reality: a tool the configuration does not expose is
                # not callable, so the version flags are genuinely tested.
                return _Response(
                    content=[_Text(f"[stub: {name} not available in this version]")]
                )
            return _Response(content=[_ToolUse(name=name, input=arguments)])

        return _Response(content=[_Text(str(step))])
