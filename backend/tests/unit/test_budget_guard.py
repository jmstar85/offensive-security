"""Unit tests for BudgetGuard (plan v3.2.1 §1.2).

Heavy integration (real spend aggregation) is covered in P3 integration tests.
P0 tests verify the cap-exhausted path and the per-user vs team-pool routing.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.budget_guard import BudgetGuard


def _user(team_id=None):
    return SimpleNamespace(id="u", role="member", team_id=team_id)


@pytest.mark.asyncio
async def test_check_returns_remaining_when_under_cap(db):
    """spent_today defaults to 0 in P0; remaining must equal the cap."""
    guard = BudgetGuard(cap_usd=Decimal("5.00"))
    res = await guard.check(db, _user())
    assert res.remaining_usd == Decimal("5.00")
    assert res.cap_usd == Decimal("5.00")
    assert res.pool == "user"


@pytest.mark.asyncio
async def test_check_uses_team_pool_when_team_id_set(db):
    guard = BudgetGuard(cap_usd=Decimal("5.00"))
    res = await guard.check(db, _user(team_id="t-1"))
    assert res.pool == "team"


@pytest.mark.asyncio
async def test_check_raises_429_when_exhausted(monkeypatch):
    guard = BudgetGuard(cap_usd=Decimal("5.00"))
    monkeypatch.setattr(
        guard, "_spent_today", AsyncMock(return_value=Decimal("5.00"))
    )
    with pytest.raises(HTTPException) as ei:
        await guard.check(db=None, user=_user())
    assert ei.value.status_code == 429
    assert ei.value.detail["error"] == "daily_budget_exhausted"


@pytest.mark.asyncio
async def test_check_raises_429_when_over_cap(monkeypatch):
    guard = BudgetGuard(cap_usd=Decimal("5.00"))
    monkeypatch.setattr(
        guard, "_spent_today", AsyncMock(return_value=Decimal("6.50"))
    )
    with pytest.raises(HTTPException) as ei:
        await guard.check(db=None, user=_user())
    assert ei.value.status_code == 429
