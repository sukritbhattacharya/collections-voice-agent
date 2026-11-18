"""The scripted customer.

Plays one persona against the agent. Runs on a cheap model: staying in
character and following a short behavioural script is a much lower bar than
the agent's job, and the simulator is not what is being measured.

The simulator is told to be difficult where the scenario calls for it. A
cooperative simulator produces a flattering transcript and a useless result.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

#: The simulator says this when the conversation is over. Checked as a prefix
#: as well as a bare token, because models like to add a full stop.
END_MARKER = "[END]"

_SYSTEM = """\
You are playing a customer in a simulated phone call, for testing a collections \
voice agent. Stay in character at all times.

{persona}

Rules for how you reply:
- Reply with ONLY what the customer says out loud. No narration, no stage \
directions, no quotation marks, no labels.
- One or two sentences. This is a phone call, not an essay.
- Follow the behaviour described above in order. Do not skip ahead.
- Never break character, never mention that this is a test, and never help the \
agent do its job.
- When the conversation has genuinely reached its end -- you have said goodbye, \
or you have been told a colleague will take over -- reply with exactly {end} \
and nothing else.
"""


@dataclass
class Simulator:
    persona: str
    model: str = field(
        default_factory=lambda: os.getenv("SIMULATOR_MODEL", "claude-haiku-5-5")
    )
    history: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        from anthropic import Anthropic

        self._client = Anthropic()
        self._system = _SYSTEM.format(persona=self.persona, end=END_MARKER)

    def reply_to(self, agent_said: str) -> str | None:
        """Respond to the agent. Returns None when the customer has hung up."""
        self.history.append({"role": "user", "content": agent_said or "(silence)"})

        response = self._client.messages.create(
            model=self.model,
            max_tokens=256,
            system=self._system,
            messages=self.history,
            output_config={"effort": "low"},
        )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        self.history.append({"role": "assistant", "content": text or "..."})

        if END_MARKER in text.upper():
            remainder = re.sub(re.escape(END_MARKER), "", text, flags=re.I).strip()
            return remainder or None
        # An empty reply is silence, which ends the call. Passing it on would
        # send an empty user message and the request would be rejected.
        return text or None
