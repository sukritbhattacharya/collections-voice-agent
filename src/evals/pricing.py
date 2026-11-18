"""Token prices, so a run can report what it cost.

Cost per call is the number that decides whether a collections bot is viable
at portfolio scale -- a few hundred thousand calls a month makes a 20x model
price difference a business decision, not an engineering preference. A harness
that reports it answers "why this model" better than a pricing page does.
"""

from __future__ import annotations

#: USD per million tokens, (input, output). Update alongside the model list.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "stub": (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
    return input_tokens / 1e6 * rate_in + output_tokens / 1e6 * rate_out


def fmt(amount: float) -> str:
    if amount == 0:
        return "$0"
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"
