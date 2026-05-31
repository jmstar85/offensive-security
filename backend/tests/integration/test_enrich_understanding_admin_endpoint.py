"""Integration: POST /pentest-sessions/{id}/enrich-understanding access control.

Verifies:
  - Non-admin (MEMBER) → 403
  - TEAM_ADMIN → 200 + coordinator_revision_no incremented
  - ADMIN → 200 + coordinator_revision_no incremented
  - Audit log emits action='coordinator.understanding_enriched'
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, Team
from app.models.session import PentestSession


def _make_user(role: UserRole) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = f"{role.value}_{uuid.uuid4().hex[:6]}@example.com"
    u.full_name = f"{role.value.title()} User"
    u.role = role.value
    u.is_active = True
    u.team_id = uuid.uuid4()
    return u


def _make_session(project_id: uuid.UUID) -> PentestSession:
    s = PentestSession(
        project_id=project_id,
        prompt="test prompt",
        understanding_json={"raw_signals": {"target": "example.com"}},
        coordinator_revision_no=0,
    )
    s.id = uuid.uuid4()
    return s


class _FakeDB:
    """Minimal async DB fake; flush populates id+created_at for added objects."""

    def __init__(self, session: PentestSession):
        self._session = session
        self._added: list = []

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._session
        return result

    def add(self, obj):
        self._added.append(obj)

    async def flush(self):
        for obj in self._added:
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            import datetime
            if not getattr(obj, "created_at", None):
                obj.created_at = datetime.datetime.utcnow()


@pytest.mark.asyncio
async def test_enrich_understanding_requires_admin():
    """MEMBER user → 403; TEAM_ADMIN and ADMIN → 200."""
    from app.api.v1.coordinator import enrich_understanding, EnrichUnderstandingRequest

    project_id = uuid.uuid4()
    session_obj = _make_session(project_id)
    db = _FakeDB(session_obj)

    member = _make_user(UserRole.MEMBER)
    with pytest.raises(HTTPException) as exc_info:
        await enrich_understanding(
            session_id=session_obj.id,
            body=EnrichUnderstandingRequest(manual_signals={"extra": "data"}),
            db=db,
            current_user=member,
        )
    assert exc_info.value.status_code == 403

    # TEAM_ADMIN succeeds
    session_obj.coordinator_revision_no = 0
    db2 = _FakeDB(session_obj)
    team_admin = _make_user(UserRole.TEAM_ADMIN)
    resp = await enrich_understanding(
        session_id=session_obj.id,
        body=EnrichUnderstandingRequest(manual_signals={"extra": "data"}),
        db=db2,
        current_user=team_admin,
    )
    assert resp.coordinator_revision_no == 1

    # ADMIN succeeds
    session_obj.coordinator_revision_no = 0
    db3 = _FakeDB(session_obj)
    admin = _make_user(UserRole.ADMIN)
    resp2 = await enrich_understanding(
        session_id=session_obj.id,
        body=EnrichUnderstandingRequest(manual_signals={"extra": "data2"}),
        db=db3,
        current_user=admin,
    )
    assert resp2.coordinator_revision_no == 1


@pytest.mark.asyncio
async def test_enrich_understanding_bumps_revision_no():
    """Each call increments coordinator_revision_no by 1."""
    from app.api.v1.coordinator import enrich_understanding, EnrichUnderstandingRequest

    project_id = uuid.uuid4()
    session_obj = _make_session(project_id)
    session_obj.coordinator_revision_no = 5

    db = _FakeDB(session_obj)
    admin = _make_user(UserRole.ADMIN)

    resp = await enrich_understanding(
        session_id=session_obj.id,
        body=EnrichUnderstandingRequest(manual_signals={"new_key": "new_val"}),
        db=db,
        current_user=admin,
    )
    assert resp.coordinator_revision_no == 6
    assert session_obj.coordinator_revision_no == 6
    assert session_obj.understanding_json["raw_signals"]["new_key"] == "new_val"


@pytest.mark.asyncio
async def test_enrich_understanding_emits_audit():
    """Audit log entry with action='coordinator.understanding_enriched' is added."""
    from app.api.v1.coordinator import enrich_understanding, EnrichUnderstandingRequest
    from app.models.audit import AuditLog

    project_id = uuid.uuid4()
    session_obj = _make_session(project_id)
    db = _FakeDB(session_obj)
    admin = _make_user(UserRole.ADMIN)

    await enrich_understanding(
        session_id=session_obj.id,
        body=EnrichUnderstandingRequest(manual_signals={"sig": "val"}),
        db=db,
        current_user=admin,
    )

    audit_entries = [obj for obj in db._added if isinstance(obj, AuditLog)]
    assert len(audit_entries) == 1
    assert audit_entries[0].action == "coordinator.understanding_enriched"
    assert audit_entries[0].actor_id == admin.id
    assert str(session_obj.id) == audit_entries[0].target_id
