"""WorkflowService.delete_session — permanently removes a session + all child
rows across the mixed-cascade FK graph.

The three children whose FK to ``pentest_sessions`` is a plain (non-cascade) FK
— ``agent_executions``, ``attack_scenarios``, ``reports`` — must be deleted
explicitly (else the session DELETE raises a FK violation). The cascade children
(``workflow_messages``, ``terminal_lines``, …) go with the session row. Also
covers the 409 (running) and 404 (cross-team / missing) guards.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.report import Report
from app.models.session import (
    AgentExecution,
    AttackScenario,
    PentestSession,
    TerminalLine,
    WorkflowMessage,
)
from app.models.user import UserRole
from app.orchestrator.workflow_service import WorkflowService


def _user(team_id=None, role=UserRole.MEMBER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="op@example.com",
        full_name="Op",
        role=role,
        is_active=True,
        team_id=team_id or uuid.uuid4(),
    )


async def _seed_session(db, *, team_id=None, status="completed") -> PentestSession:
    from app.models.project import Project

    project = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(project)
    await db.flush()
    s = PentestSession(
        project_id=project.id,
        prompt="x",
        status=status,
        interview_state="ready_for_review",
        interview_turn_count=1,
        team_id=team_id,
    )
    db.add(s)
    await db.flush()
    return s


async def _count(db, model, session_id) -> int:
    col = model.pentest_session_id if hasattr(model, "pentest_session_id") else model.session_id
    return (
        await db.execute(select(func.count()).select_from(model).where(col == session_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_delete_session_removes_session_and_all_children(db):
    """Seed a session with one row in every child table (both non-cascade and
    cascade), then delete it and assert everything is gone with no FK error."""
    user = _user()
    s = await _seed_session(db, team_id=user.team_id)
    sid = s.id

    # Non-cascade children (must be deleted explicitly).
    execution = AgentExecution(session_id=sid, agent_type="nmap", status="completed")
    db.add(execution)
    db.add(AttackScenario(session_id=sid, steps_json={"steps": []}))
    db.add(Report(session_id=sid, summary="r", findings_json={}))
    # Cascade children (go with the session row); terminal_lines points at the
    # execution via ON DELETE SET NULL, so its execution must be deletable first.
    db.add(WorkflowMessage(pentest_session_id=sid, role="user", content="hi", turn_index=0))
    await db.flush()
    db.add(TerminalLine(session_id=sid, execution_id=execution.id, seq=1, line="out"))
    await db.flush()

    # sanity: children exist
    assert await _count(db, AgentExecution, sid) == 1
    assert await _count(db, AttackScenario, sid) == 1
    assert await _count(db, Report, sid) == 1
    assert await _count(db, WorkflowMessage, sid) == 1
    assert await _count(db, TerminalLine, sid) == 1

    await WorkflowService(db).delete_session(session_id=sid, user=user)
    await db.flush()

    # session row gone
    assert (
        await db.execute(select(PentestSession).where(PentestSession.id == sid))
    ).scalar_one_or_none() is None
    # every child gone
    assert await _count(db, AgentExecution, sid) == 0
    assert await _count(db, AttackScenario, sid) == 0
    assert await _count(db, Report, sid) == 0
    assert await _count(db, WorkflowMessage, sid) == 0
    assert await _count(db, TerminalLine, sid) == 0


@pytest.mark.asyncio
async def test_delete_running_session_is_rejected_409(db):
    user = _user()
    s = await _seed_session(db, team_id=user.team_id, status="running")
    with pytest.raises(HTTPException) as exc:
        await WorkflowService(db).delete_session(session_id=s.id, user=user)
    assert exc.value.status_code == 409
    # still present
    assert (
        await db.execute(select(PentestSession).where(PentestSession.id == s.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_other_teams_session_is_404(db):
    s = await _seed_session(db, team_id=uuid.uuid4(), status="completed")
    other_user = _user(team_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await WorkflowService(db).delete_session(session_id=s.id, user=other_user)
    assert exc.value.status_code == 404
    assert (
        await db.execute(select(PentestSession).where(PentestSession.id == s.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_missing_session_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await WorkflowService(db).delete_session(session_id=uuid.uuid4(), user=_user())
    assert exc.value.status_code == 404
