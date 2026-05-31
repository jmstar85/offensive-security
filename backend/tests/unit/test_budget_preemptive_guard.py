"""Tests for BudgetGuard Layer-A and Layer-B pre-emptive checks (PR1.5)."""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.orchestrator.llm.budget_guard import BudgetGuard, SessionBudgetExceeded


def _make_guard(accum_usd: float, cap_usd: float) -> BudgetGuard:
    db = AsyncMock()
    session_id = uuid.uuid4()
    guard = BudgetGuard(db=db, session_id=session_id, hard_cap_usd=cap_usd)
    guard._current_accum = AsyncMock(return_value=accum_usd)
    return guard


@pytest.mark.asyncio
async def test_layer_a_passes_when_under_cap() -> None:
    """budget=10, accum=8, estimate=2.5 (5 tasks × 0.5 USD) → passes (10.5 > 10 is False here)."""
    guard = _make_guard(accum_usd=8.0, cap_usd=10.0)
    # 8 + 2.5 = 10.5 > 10 → should RAISE
    # Let's use a value that passes: 8 + 1.9 = 9.9 < 10
    await guard.layer_a_check(estimated_cost_usd=1.9)


@pytest.mark.asyncio
async def test_layer_a_raises_when_would_overshoot() -> None:
    """budget=10, accum=9.5, estimate=5×0.5=2.5 → 9.5+2.5=12 > 10 → Layer-A raises."""
    guard = _make_guard(accum_usd=9.5, cap_usd=10.0)
    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await guard.layer_a_check(estimated_cost_usd=2.5)
    assert exc_info.value.reason == "layer_a_aggregate"


@pytest.mark.asyncio
async def test_layer_a_exact_threshold_passes() -> None:
    """budget=10, accum=8.0, estimate=2.0 → 8+2=10 is NOT > 10 → passes."""
    guard = _make_guard(accum_usd=8.0, cap_usd=10.0)
    await guard.layer_a_check(estimated_cost_usd=2.0)


@pytest.mark.asyncio
async def test_layer_b_raises_when_single_call_overshoots() -> None:
    """budget=5, accum=0, marginal=10 → 0+10=10 > 5 → Layer-B raises."""
    guard = _make_guard(accum_usd=0.0, cap_usd=5.0)
    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await guard.layer_b_check(actual_marginal_cost_usd=10.0)
    assert exc_info.value.reason == "layer_b_marginal"


@pytest.mark.asyncio
async def test_layer_b_passes_when_under_cap() -> None:
    """budget=5, accum=3, marginal=1.5 → 4.5 <= 5 → passes."""
    guard = _make_guard(accum_usd=3.0, cap_usd=5.0)
    await guard.layer_b_check(actual_marginal_cost_usd=1.5)


@pytest.mark.asyncio
async def test_layer_b_raises_at_marginal_boundary() -> None:
    """budget=5, accum=4.9, marginal=0.2 → 5.1 > 5 → Layer-B raises."""
    guard = _make_guard(accum_usd=4.9, cap_usd=5.0)
    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await guard.layer_b_check(actual_marginal_cost_usd=0.2)
    assert exc_info.value.reason == "layer_b_marginal"


def test_semaphore_size_normal() -> None:
    guard = _make_guard(accum_usd=0.0, cap_usd=10.0)
    assert guard.semaphore_size_for_budget(headroom_usd=8.0, avg_cost_per_task=1.0) == 8


def test_semaphore_size_clamped_to_16() -> None:
    guard = _make_guard(accum_usd=0.0, cap_usd=100.0)
    assert guard.semaphore_size_for_budget(headroom_usd=100.0, avg_cost_per_task=0.01) == 16


def test_semaphore_size_clamped_to_1() -> None:
    guard = _make_guard(accum_usd=0.0, cap_usd=1.0)
    # floor(0.3 / 1.0) = 0 → clamped to 1
    assert guard.semaphore_size_for_budget(headroom_usd=0.3, avg_cost_per_task=1.0) == 1


def test_semaphore_size_zero_avg_returns_1() -> None:
    guard = _make_guard(accum_usd=0.0, cap_usd=10.0)
    assert guard.semaphore_size_for_budget(headroom_usd=10.0, avg_cost_per_task=0.0) == 1
