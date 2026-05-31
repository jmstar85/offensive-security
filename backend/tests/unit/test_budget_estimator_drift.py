"""Tests for BudgetGuard estimator drift EMA tracking (PR1.5 / SF-CRITIC-2)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

import app.orchestrator.llm.budget_guard as bg_module
from app.orchestrator.llm.budget_guard import BudgetGuard, _provider_ema, _update_estimator_ema


def _make_guard(cap_usd: float = 100.0) -> BudgetGuard:
    db = AsyncMock()
    guard = BudgetGuard(db=db, session_id=uuid.uuid4(), hard_cap_usd=cap_usd)
    guard._current_accum = AsyncMock(return_value=0.0)
    return guard


def setup_function() -> None:
    """Reset module-level EMA state before each test."""
    _provider_ema.clear()
    bg_module._provider_samples.clear()


def test_ema_initialises_to_first_ratio() -> None:
    """First sample initialises EMA to actual/estimate ratio."""
    provider = "anthropic"
    ratio = _update_estimator_ema(provider, actual=1.0, estimate=0.5)
    # First call: EMA = alpha * ratio + (1-alpha) * ratio = ratio = 2.0
    assert abs(ratio - 2.0) < 1e-9


def test_ema_tracks_toward_new_ratio() -> None:
    """Repeated samples with ratio=1.0 should pull EMA toward 1.0."""
    provider = "openai"
    # Seed with a high initial ratio.
    _provider_ema[provider] = 3.0

    # Feed 50 samples with ratio=1.0; EMA should converge toward 1.0.
    for _ in range(50):
        ema = _update_estimator_ema(provider, actual=1.0, estimate=1.0)

    assert ema < 2.0, f"EMA should have pulled toward 1.0, got {ema}"
    assert ema > 0.9, f"EMA should not undershoot, got {ema}"


def test_ema_does_not_update_on_zero_estimate() -> None:
    """Zero estimate is ignored; EMA stays at previous value."""
    provider = "google"
    _provider_ema[provider] = 1.5
    result = _update_estimator_ema(provider, actual=1.0, estimate=0.0)
    assert result == 1.5


@pytest.mark.asyncio
async def test_record_updates_prometheus_gauge() -> None:
    """record() updates the estimator_drift gauge after each call."""
    provider = "anthropic"
    guard = _make_guard()

    with patch.object(
        bg_module.metrics.budget_guard_estimator_drift, "set"
    ) as mock_set:
        await guard.record(
            provider=provider,
            model="claude-sonnet-4-6",
            tokens_in=100,
            tokens_out=50,
            actual_cost_usd=0.002,
            pre_call_estimate=0.001,
        )
        mock_set.assert_called_once()
        call_kwargs = mock_set.call_args
        assert call_kwargs is not None
        # The gauge value should be the updated EMA (actual=0.002, estimate=0.001 → ratio=2.0)
        value_arg = call_kwargs[1].get("value") or call_kwargs[0][0]
        assert value_arg > 0


@pytest.mark.asyncio
async def test_record_skips_gauge_on_zero_estimate() -> None:
    """record() does not update the gauge when pre_call_estimate=0."""
    guard = _make_guard()

    with patch.object(
        bg_module.metrics.budget_guard_estimator_drift, "set"
    ) as mock_set:
        await guard.record(
            provider="anthropic",
            model="claude-sonnet-4-6",
            tokens_in=100,
            tokens_out=50,
            actual_cost_usd=0.002,
            pre_call_estimate=0.0,
        )
        mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_record_increments_token_counters() -> None:
    """record() increments llm_tokens_total for both prompt and completion kinds."""
    from app.observability.metrics import metrics

    guard = _make_guard()
    await guard.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        tokens_in=200,
        tokens_out=80,
        actual_cost_usd=0.003,
        pre_call_estimate=0.003,
    )

    prompt_count = metrics.llm_tokens_total.value(
        provider="anthropic", model="claude-sonnet-4-6", kind="prompt"
    )
    completion_count = metrics.llm_tokens_total.value(
        provider="anthropic", model="claude-sonnet-4-6", kind="completion"
    )
    assert prompt_count >= 200.0
    assert completion_count >= 80.0
