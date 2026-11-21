"""Per-turn latency, broken down by stage.

"It feels laggy" is not actionable. "Time to first audio is 1.9s at p95, of
which text-to-speech is 1.1s" names the component to swap. Four marks per
turn:

    end of customer speech -> transcript final -> first model token
      -> first audio byte -> audio reaching the caller

Recorded on every call and carried in the outcome payload, so a device- or
network-specific problem shows up in the data rather than as an impression.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TurnTiming:
    started: float = field(default_factory=time.perf_counter)
    stt_final_ms: int | None = None
    llm_first_token_ms: int | None = None
    tts_first_byte_ms: int | None = None
    audio_out_ms: int | None = None

    def mark(self, stage: str) -> None:
        elapsed = int((time.perf_counter() - self.started) * 1000)
        setattr(self, f"{stage}_ms", elapsed)

    def as_dict(self) -> dict[str, int | None]:
        return {
            "stt_final_ms": self.stt_final_ms,
            "llm_first_token_ms": self.llm_first_token_ms,
            "tts_first_byte_ms": self.tts_first_byte_ms,
            "audio_out_ms": self.audio_out_ms,
        }


@dataclass
class CallTelemetry:
    turns: list[TurnTiming] = field(default_factory=list)

    def begin_turn(self) -> TurnTiming:
        timing = TurnTiming()
        self.turns.append(timing)
        return timing

    def _percentile(self, values: list[int], pct: float) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]

    def summary(self) -> dict[str, int | None]:
        """End-of-speech to audio out -- the number the caller experiences."""
        complete = [t.audio_out_ms for t in self.turns if t.audio_out_ms is not None]
        return {
            "p50_ms": self._percentile(complete, 0.50),
            "p95_ms": self._percentile(complete, 0.95),
            "turns_measured": len(complete),
            # The raw turns, so a p95 can be pooled across calls. Percentiles
            # do not average: a median of per-call p95s is not a p95. See
            # D-065.
            "turns_ms": list(complete),
        }

    def stage_breakdown(self) -> dict[str, int | None]:
        """Median per stage, to say which component is the bottleneck."""
        def med(attr: str) -> int | None:
            vals = [
                getattr(t, attr) for t in self.turns if getattr(t, attr) is not None
            ]
            return self._percentile(vals, 0.50)

        return {
            "stt_final_ms": med("stt_final_ms"),
            "llm_first_token_ms": med("llm_first_token_ms"),
            "tts_first_byte_ms": med("tts_first_byte_ms"),
            "audio_out_ms": med("audio_out_ms"),
        }
