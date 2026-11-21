"""Report M5 from the raw turn latencies, pooled across calls.

M5 is p95 of end-of-speech to first audio out. That is a percentile over
*turns*, so it has to be computed from every turn in the window -- a median,
or a mean, of per-call p95s is not a p95 of anything. Calls recorded before
`latency.turns_ms` existed carry only a summary and are counted as
unpoolable rather than quietly folded in. See D-065.

    uv run python -m src.evals.latency
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD = ROOT / "results" / "outcomes.jsonl"
TARGET_MS = 1500

#: Below this many turns a p95 is the single worst observation, which is an
#: anecdote with a percentile sign on it.
MIN_TURNS = 20


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def main() -> None:
    if not RECORD.exists():
        print("  no calls recorded yet")
        return

    pooled: list[int] = []
    by_device: dict[str, list[int]] = {}
    calls = unpoolable = 0

    for line in RECORD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if (r.get("client") or {}).get("surface") != "web":
            continue
        lat = r.get("latency") or {}
        turns = lat.get("turns_ms") or []
        if not turns:
            if lat.get("turns_measured"):
                unpoolable += 1
            continue
        calls += 1
        pooled.extend(turns)
        device = (r.get("client") or {}).get("platform") or "unknown"
        by_device.setdefault(device, []).extend(turns)

    print(f"\n  M5 — p95 end-of-speech to first audio, target {TARGET_MS} ms\n")
    if not pooled:
        print("  No call carries raw turn latencies yet.")
        if unpoolable:
            print(f"  {unpoolable} earlier calls hold only a summary and cannot")
            print("  be pooled. Place fresh calls to produce the number.")
        print(f"\n  Need at least {MIN_TURNS} turns, so roughly"
              f" {-(-MIN_TURNS // 6)} calls at ~6 turns each.")
        return

    p50, p95 = _pct(pooled, 0.50), _pct(pooled, 0.95)
    verdict = "MET" if p95 and p95 <= TARGET_MS else "MISSED"
    print(f"  pooled over {len(pooled)} turns from {calls} calls")
    print(f"    p50  {p50} ms")
    print(f"    p95  {p95} ms   -> {verdict}")
    if len(pooled) < MIN_TURNS:
        print(f"\n  Thin: {len(pooled)} turns. Below {MIN_TURNS} the p95 is"
              " essentially the worst\n  single turn. Treat it as directional.")
    for device, turns in sorted(by_device.items()):
        print(f"    {device:9} {len(turns):3} turns   p50 {_pct(turns, 0.50)}"
              f"   p95 {_pct(turns, 0.95)}")
    if unpoolable:
        print(f"\n  {unpoolable} earlier calls excluded: summary only, no raw turns.")


if __name__ == "__main__":
    main()
