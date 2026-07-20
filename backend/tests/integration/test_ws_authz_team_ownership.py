"""Regression: ws._authorize_session_access team-ownership branch.

The prior code checked ``project.team_id`` but ``Project`` has no ``team_id``
column, so every non-admin WebSocket connect raised AttributeError. The team
linkage lives on ``PentestSession.team_id`` (set at create). These tests drive
the real ``_authorize_session_access`` against the test DB (async_session()
patched to yield the test session) and assert the same-team / other-team /
admin / unknown-session outcomes.
"""
from __future__ import annotations

import uuid

import pytest

from app.api.v1 import ws as ws_mod
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole


class _WrapSession:
    """Stand in for the app's ``async_session()`` CM, yielding the test
    session (whose flushed rows the auth query must see) without closing it."""

    def __init__(self, session) -> None:
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *exc) -> bool:
        return False


async def _seed(db, *, role=UserRole.MEMBER, session_team=None):
    sfx = uuid.uuid4().hex[:6]
    team = Team(name=f"t-{sfx}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{sfx}@kt.com", password_hash="x" * 60, full_name="U",
        role=role, team_id=team.id,
    )
    project = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(user)
    db.add(project)
    await db.flush()
    session = PentestSession(
        project_id=project.id, prompt="x", status="completed",
        interview_state="ready_for_review", interview_turn_count=1,
        team_id=(session_team if session_team is not None else team.id),
    )
    db.add(session)
    await db.flush()
    return user, session


def _patch(monkeypatch, db, user):
    monkeypatch.setattr(ws_mod, "async_session", lambda: _WrapSession(db))
    monkeypatch.setattr(ws_mod, "decode_access_token", lambda _tok: str(user.id))


@pytest.mark.asyncio
async def test_same_team_member_is_authorized(db, monkeypatch):
    user, session = await _seed(db)
    _patch(monkeypatch, db, user)
    assert await ws_mod._authorize_session_access("tok", session.id) == (True, 0)


@pytest.mark.asyncio
async def test_other_team_member_is_forbidden_4003(db, monkeypatch):
    user, session = await _seed(db, session_team=uuid.uuid4())
    _patch(monkeypatch, db, user)
    ok, code = await ws_mod._authorize_session_access("tok", session.id)
    assert ok is False
    assert code == 4003


@pytest.mark.asyncio
async def test_admin_is_authorized_for_any_team_session(db, monkeypatch):
    user, session = await _seed(db, role=UserRole.ADMIN, session_team=uuid.uuid4())
    _patch(monkeypatch, db, user)
    assert await ws_mod._authorize_session_access("tok", session.id) == (True, 0)


@pytest.mark.asyncio
async def test_unknown_session_is_4004(db, monkeypatch):
    user, _ = await _seed(db)
    _patch(monkeypatch, db, user)
    ok, code = await ws_mod._authorize_session_access("tok", uuid.uuid4())
    assert ok is False
    assert code == 4004
