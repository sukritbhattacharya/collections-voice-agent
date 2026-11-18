"""Pre-model scan of what the customer said.

The brief requires the agent to stop the pitch and hand over when a customer is
abusive, or discloses a medical emergency or job loss. Leaving that judgement to
the model is the wrong place for it: a missed hand-over on an abusive or
distressed call is the failure that ends up in a complaint, and it is exactly
the kind of thing a model under instruction-following pressure drops.

So the decision is taken here, deterministically, before the model is consulted.
The model is then told what has happened and asked to close the call gracefully
-- it controls the wording, not the outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).parent / "rules.yaml"


@dataclass(frozen=True)
class TripwireHit:
    trigger_id: str
    reason: str
    matched_text: str


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, str, list[re.Pattern[str]]]]:
    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    out = []
    for trig in raw.get("input_triggers", []):
        pats = [re.compile(p, re.IGNORECASE) for p in trig["patterns"]]
        out.append((trig["id"], trig["reason"], pats))
    return out


def scan(utterance: str) -> TripwireHit | None:
    """Return the first trigger this utterance fires, if any.

    Order in the rules file is priority order: abuse first, because an abusive
    customer who also mentions a job loss is still an abuse hand-over and goes
    to a different queue.
    """
    if not utterance or not utterance.strip():
        return None

    for trigger_id, reason, patterns in _compiled():
        for pat in patterns:
            m = pat.search(utterance)
            if m:
                return TripwireHit(
                    trigger_id=trigger_id,
                    reason=reason,
                    matched_text=m.group(0),
                )
    return None
