"""Performer skeleton tests (v4.0 P1).

P1 ships the engine skeleton only. Tests verify:
- Performer can be instantiated with a db session and session_id.
- `register_role(role)` adds the role to the per-session catalog.
- `run_session()` returns an empty list when no roles are registered.
- Concurrency cap (`max_concurrent_performer_sessions`) is enforced.
- `_dispatch_tool` raises NotImplementedError until P2a wires it.

P2a will replace these stubs with the role-loop runner + ADR-005 tool dispatch.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.orchestrator import performer as performer_module
from app.orchestrator.performer import (
    Performer,
    PerformerConcurrencyLimit,
    PERFORMER_MAX_ITER,
)
from app.orchestrator.roles.base import Role, RoleResult


@dataclass
class _FakeRole(Role):
    """Concrete Role for testing the registry contract without a real LLM."""

    async def run(self, performer: Performer, context: dict[str, Any]) -> RoleResult:
        return RoleResult(role_name=self.name, finished=True)


@pytest.fixture
def _reset_active_performers():
    """Ensure each test starts with a clean concurrency-cap set."""
    performer_module._active_performers.clear()
    yield
    performer_module._active_performers.clear()


def test_performer_max_iter_constant_matches_settings():
    from app.core.config import settings

    assert PERFORMER_MAX_ITER == settings.performer_max_iter
    assert PERFORMER_MAX_ITER == 64  # default per v4.0 plan ADR-003


def test_performer_instantiation():
    db = AsyncMock()
    sid = uuid.uuid4()
    p = Performer(db=db, session_id=sid)
    assert p.state.session_id == sid
    assert p.state.roles == {}
    assert p.state.iteration == 0


def test_register_role():
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    role = _FakeRole(
        name="fake",
        system_prompt="test",
        llm_model="claude-sonnet-4-6",
        tools_allowed=["nmap"],
        max_tool_calls=5,
    )
    p.register_role(role)
    assert "fake" in p.state.roles
    assert p.state.roles["fake"] is role


@pytest.mark.asyncio
async def test_run_session_no_roles_returns_empty(_reset_active_performers):
    """P1 skeleton: run_session() with no roles is a no-op returning []."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    result = await p.run_session()
    assert result == []


@pytest.mark.asyncio
async def test_dispatch_tool_rejects_unknown_slug():
    """P2a dispatcher: unknown tool slugs are rejected up front."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    result = await p._dispatch_tool("not_a_real_tool", {"intent": "port_scan", "config": {}})
    assert result["approved"] is False
    assert "unknown_tool_slug" in result["blocked_reason"]


@pytest.mark.asyncio
async def test_concurrency_cap_enforced(monkeypatch, _reset_active_performers):
    """ADR-003 + SF-3: at-cap session start raises PerformerConcurrencyLimit."""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "max_concurrent_performer_sessions", 2)

    # Pre-fill the active set to the cap, then attempt one more.
    performer_module._active_performers.add(uuid.uuid4())
    performer_module._active_performers.add(uuid.uuid4())

    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    with pytest.raises(PerformerConcurrencyLimit):
        await p.run_session()


@pytest.mark.asyncio
async def test_concurrency_lease_releases_on_success(_reset_active_performers):
    """Successful run_session leaves _active_performers empty afterward."""
    db = AsyncMock()
    sid = uuid.uuid4()
    p = Performer(db=db, session_id=sid)
    await p.run_session()
    assert sid not in performer_module._active_performers
    assert len(performer_module._active_performers) == 0
