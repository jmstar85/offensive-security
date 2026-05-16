"""Per-model input/output USD per 1k tokens. Single source of truth.

Plan v3.2.1 §1.2 — split out from former ModelRouter god-class (Critic D-8).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Rate:
    input_per_1k: Decimal
    output_per_1k: Decimal


class Pricing:
    """Anthropic per-model pricing. Deterministic, no I/O."""

    RATES: dict[str, Rate] = {
        "claude-sonnet-4-6": Rate(
            input_per_1k=Decimal("0.003"),
            output_per_1k=Decimal("0.015"),
        ),
        "claude-opus-4-6": Rate(
            input_per_1k=Decimal("0.015"),
            output_per_1k=Decimal("0.075"),
        ),
    }

    def cost(self, model_id: str, tokens_in: int, tokens_out: int) -> Decimal:
        """Return cost in USD for the given token counts."""
        rate = self.RATES.get(model_id)
        if rate is None:
            raise ValueError(f"Unknown model_id for pricing: {model_id}")
        input_cost = (rate.input_per_1k * Decimal(tokens_in)) / Decimal(1000)
        output_cost = (rate.output_per_1k * Decimal(tokens_out)) / Decimal(1000)
        return input_cost + output_cost
