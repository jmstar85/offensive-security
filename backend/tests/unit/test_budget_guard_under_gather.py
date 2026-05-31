"""Adversarial gather-fanout tests for the two-layer pre-emptive budget guard (PR1.5 / MF2).

Covers:
- 4 tasks × 2 USD = 8 USD, cap=5, accum=0 → Layer-A raises before any task fires.
- If Layer-A is bypassed, Layer-B still fires per-task when marginal cost exceeds remaining.
"""
from __future__ import annotations

import asyncio
import uuid
from contextvars import copy_context
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.llm.budget_guard import BudgetGuard, SessionBudgetExceeded
from app.orchestrator.llm.context import CURRENT_USER_ID


def _make_guard(accum_usd: float, cap_usd: float) -> BudgetGuard:
    db = AsyncMock()
    session_id = uuid.uuid4()
    guard = BudgetGuard(db=db, session_id=session_id, hard_cap_usd=cap_usd)
    guard._current_accum = AsyncMock(return_value=accum_usd)
    return guard


@pytest.mark.asyncio
async def test_layer_a_blocks_gather_fanout() -> None:
    """4 tasks × 2 USD = 8 USD aggregate, cap=5, accum=0 → Layer-A raises before gather."""
    guard = _make_guard(accum_usd=0.0, cap_usd=5.0)
    n_tasks = 4
    cost_per_task = 2.0
    estimated_total = n_tasks * cost_per_task  # 8.0 USD

    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await guard.layer_a_check(estimated_cost_usd=estimated_total)

    assert exc_info.value.reason == "layer_a_aggregate"


@pytest.mark.asyncio
async def test_layer_b_fires_per_task_when_layer_a_bypassed() -> None:
    """If Layer-A is not called, Layer-B catches the overshoot inside each task."""
    cap = 5.0
    per_task_cost = 2.0
    # Simulate 3 tasks where accum grows after each; Layer-B must fire on task 3.

    accum = 0.0

    async def simulated_task(task_cost: float) -> None:
        nonlocal accum
        guard = _make_guard(accum_usd=accum, cap_usd=cap)
        await guard.layer_b_check(actual_marginal_cost_usd=task_cost)
        accum += task_cost  # only reached if check passes

    # Task 1: 0 + 2 = 2 ≤ 5 → passes
    await simulated_task(per_task_cost)
    assert accum == 2.0

    # Task 2: 2 + 2 = 4 ≤ 5 → passes
    await simulated_task(per_task_cost)
    assert accum == 4.0

    # Task 3: 4 + 2 = 6 > 5 → Layer-B raises
    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await simulated_task(per_task_cost)
    assert exc_info.value.reason == "layer_b_marginal"
    assert accum == 4.0  # accum did not advance past the failed task


@pytest.mark.asyncio
async def test_context_preserved_across_gather() -> None:
    """CURRENT_USER_ID is visible inside tasks spawned via copy_context() in a gather."""
    user_id = uuid.uuid4()

    seen: list[uuid.UUID | None] = []

    async def read_uid() -> None:
        seen.append(CURRENT_USER_ID.get())  # type: ignore[arg-type]

    CURRENT_USER_ID.set(user_id)

    ctx = copy_context()
    tasks = [
        asyncio.get_event_loop().create_task(read_uid(), context=ctx)
        for _ in range(4)
    ]
    await asyncio.gather(*tasks)

    assert all(v == user_id for v in seen), f"context leaked: {seen}"


@pytest.mark.asyncio
async def test_layer_a_passes_then_layer_b_catches_overshoot() -> None:
    """Layer-A passes with a conservative estimate; Layer-B catches the real overshoot."""
    cap = 5.0

    # Layer-A is called with a deliberately low estimate (1.0), passes.
    guard_a = _make_guard(accum_usd=4.0, cap_usd=cap)
    await guard_a.layer_a_check(estimated_cost_usd=0.5)  # 4.0 + 0.5 = 4.5 ≤ 5

    # Actual call costs 2.0 USD → Layer-B must catch it.
    guard_b = _make_guard(accum_usd=4.0, cap_usd=cap)
    with pytest.raises(SessionBudgetExceeded) as exc_info:
        await guard_b.layer_b_check(actual_marginal_cost_usd=2.0)  # 4.0 + 2.0 = 6.0 > 5
    assert exc_info.value.reason == "layer_b_marginal"
