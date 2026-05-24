"""Plan v3.2.1 §4.4 — force-ready-for-review override (Critic S5 mitigation)."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.orchestrator.workflow_service import WorkflowService


def _user(role=UserRole.MEMBER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="op@example.com",
        full_name="Op",
        role=role,
        is_active=True,
        team_id=uuid.uuid4(),
    )


_SENTINEL = object()


async def _seed_session(db, status="interviewing", draft=_SENTINEL):
    from app.models.session import PentestSession
    from app.models.project import Project

    # Project FK is required; minimal project insert.
    project = Project(
        name="p1",
        client_name="acme",
        created_by=uuid.uuid4(),
        status="active",
    )
    db.add(project)
    await db.flush()

    if draft is _SENTINEL:
        draft = {"target_summary": "t", "risk_level": "low", "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
        ]}
    s = PentestSession(
        project_id=project.id,
        prompt="x",
        status=status,
        interview_state="interviewing",
        interview_turn_count=3,
        ambiguity_score=Decimal("0.800"),
        model_id="claude-sonnet-4-6",
        draft_plan_json=draft,
    )
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_force_ready_requires_min_reason_chars(db):
    s = await _seed_session(db)
    svc = WorkflowService(db)
    user = _user()
    short = "too short"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await svc.force_ready_for_review(
            session_id=s.id, override_reason=short, user=user,
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_force_ready_advances_state_and_logs_override(db):
    s = await _seed_session(db)
    svc = WorkflowService(db)
    user = _user()
    reason = "operator confirmed scope coverage after manual verification of targets"
    updated = await svc.force_ready_for_review(
        session_id=s.id, override_reason=reason, user=user,
    )
    assert updated.status == "ready_for_review"
    assert updated.interview_state == "ready_for_review"
    assert updated.ambiguity_override_at is not None
    assert updated.ambiguity_override_by == user.id
    assert updated.ambiguity_override_reason == reason


@pytest.mark.asyncio
async def test_force_ready_rejects_session_with_empty_draft(db):
    s = await _seed_session(db, draft={})
    svc = WorkflowService(db)
    user = _user()
    reason = "operator confirmed scope coverage after manual verification of targets"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await svc.force_ready_for_review(
            session_id=s.id, override_reason=reason, user=user,
        )
    assert ei.value.status_code == 409
