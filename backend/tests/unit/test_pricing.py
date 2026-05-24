"""Unit tests for Pricing (plan v3.2.1 §1.2)."""
from decimal import Decimal

import pytest

from app.services.pricing import Pricing


def test_sonnet_1k_in_1k_out_costs_018_usd():
    """sonnet: input=0.003/1k + output=0.015/1k → 1000 in + 1000 out = 0.018."""
    assert Pricing().cost("claude-sonnet-4-6", 1000, 1000) == Decimal("0.018")


def test_opus_more_expensive_than_sonnet():
    p = Pricing()
    assert p.cost("claude-opus-4-6", 1000, 1000) > p.cost("claude-sonnet-4-6", 1000, 1000)


def test_zero_tokens_zero_cost():
    assert Pricing().cost("claude-sonnet-4-6", 0, 0) == Decimal("0")


def test_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown model_id"):
        Pricing().cost("gpt-9", 100, 100)


def test_deterministic_and_idempotent():
    p = Pricing()
    a = p.cost("claude-opus-4-6", 12345, 6789)
    b = p.cost("claude-opus-4-6", 12345, 6789)
    assert a == b
