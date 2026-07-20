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


# ── zero-step approve guard (session 0f9c5646 backstop) ──────────────────────


@pytest.mark.asyncio
async def test_force_ready_rejects_wiped_steps_list(db):
    """A truthy-but-empty {"steps": []} (the wiped-draft shape) slipped past the
    old `if not draft` guard; force-ready must now reject it with empty_plan."""
    from fastapi import HTTPException

    s = await _seed_session(db, draft={"steps": []})
    svc = WorkflowService(db)
    reason = "operator confirmed scope coverage after manual verification of targets"
    with pytest.raises(HTTPException) as ei:
        await svc.force_ready_for_review(session_id=s.id, override_reason=reason, user=_user())
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "empty_plan"
    assert s.status == "interviewing"  # unchanged


@pytest.mark.asyncio
async def test_approve_rejects_zero_step_draft(db):
    """approve() must refuse a 0-step draft with no executable plan_json — the
    scope preview is blind to step count, so this is the load-bearing backstop."""
    from fastapi import HTTPException

    s = await _seed_session(db, status="ready_for_review", draft={"steps": []})
    svc = WorkflowService(db)
    with pytest.raises(HTTPException) as ei:
        await svc.approve(session_id=s.id, user=_user())
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "empty_plan"
    assert s.approved_at is None  # never approved


@pytest.mark.asyncio
async def test_approve_allows_empty_chat_draft_when_template_plan_json_present(db):
    """A pre-seeded executable plan_json (template lane) satisfies the guard even
    when the chat draft is empty — the guard must not block template approvals."""
    s = await _seed_session(db, status="ready_for_review", draft={})
    s.plan_json = {
        "version": 1, "kind": "workflow", "edges": [],
        "steps": [{"id": "n1", "order": 1, "agent": "nmap", "action": "port_scan",
                   "config": {"scan_profile": "standard"}}],
    }
    await db.flush()
    updated = await WorkflowService(db).approve(session_id=s.id, user=_user())
    assert updated.status == "approved"
