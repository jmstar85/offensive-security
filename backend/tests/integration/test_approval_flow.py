"""Plan v3.2.1 §4.5 — approval flow re-runs WhitelistValidator on approve.

Verifies:
  - approval-preview surfaces out-of-scope step targets
  - POST /approve fails 409 when any draft step targets an out-of-scope host
  - POST /approve succeeds atomically when all targets are in scope
  - approved_at / approved_by set; draft_plan promoted to plan_json
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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


async def _seed(db, draft, whitelist_rules=None, status="ready_for_review"):
    from app.models.project import Project, Target
    from app.models.session import PentestSession
    project = Project(
        name="p", client_name="acme",
        created_by=uuid.uuid4(), status="active",
    )
    db.add(project)
    await db.flush()
    db.add(Target(
        project_id=project.id,
        ip_ranges=["10.0.0.0/24"],
        domains=["acme.com"],
        whitelist_rules=whitelist_rules or {"ip_ranges": ["10.0.0.0/24"], "domains": ["acme.com"]},
    ))
    s = PentestSession(
        project_id=project.id,
        prompt="x",
        status=status,
        interview_state="ready_for_review",
        interview_turn_count=2,
        ambiguity_score=Decimal("0.200"),
        model_id="claude-sonnet-4-6",
        draft_plan_json=draft,
    )
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_approval_preview_returns_no_violations_when_in_scope(db):
    s = await _seed(db, draft={
        "target_summary": "acme staging",
        "risk_level": "low",
        "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon",
             "tier": "passive_no_target_contact", "config": {"target": "acme.com"}},
            {"order": 2, "agent": "wappalyzer", "action": "tech_stack_inventory",
             "tier": "passive_low_touch", "config": {"host": "www.acme.com"}},
        ],
    })
    svc = WorkflowService(db)
    preview = await svc.approval_preview(session_id=s.id)
    assert preview.is_valid is True
    assert preview.violations == []
    assert preview.step_count == 2


@pytest.mark.asyncio
async def test_approval_preview_flags_out_of_scope_domain(db):
    s = await _seed(db, draft={
        "target_summary": "acme staging",
        "risk_level": "low",
        "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon",
             "tier": "passive_no_target_contact", "config": {"target": "internal.example.org"}},
        ],
    })
    svc = WorkflowService(db)
    preview = await svc.approval_preview(session_id=s.id)
    assert preview.is_valid is False
    assert any("internal.example.org" in v for v in preview.violations)


@pytest.mark.asyncio
async def test_approve_succeeds_when_all_in_scope(db):
    s = await _seed(db, draft={
        "target_summary": "acme staging",
        "risk_level": "low",
        "steps": [
            {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon",
             "tier": "passive_no_target_contact", "config": {"target": "acme.com"}},
        ],
    })
    user = _user()
    svc = WorkflowService(db)
    updated = await svc.approve(session_id=s.id, user=user)
    assert updated.status == "approved"
    assert updated.approved_at is not None
    assert updated.approved_by == user.id
    # plan_json promoted from draft_plan_json
    assert updated.plan_json == s.draft_plan_json


@pytest.mark.asyncio
async def test_approve_409_when_out_of_scope(db):
    s = await _seed(db, draft={
        "target_summary": "x", "risk_level": "low",
        "steps": [
            {"order": 1, "agent": "nmap", "action": "port_scan",
             "tier": "active_recon", "config": {"target": "192.168.99.1"}},
        ],
    })
    svc = WorkflowService(db)
    with pytest.raises(HTTPException) as ei:
        await svc.approve(session_id=s.id, user=_user())
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "out_of_scope"
    assert any("192.168.99.1" in v for v in ei.value.detail["violations"])


@pytest.mark.asyncio
async def test_approve_rejected_from_wrong_state(db):
    s = await _seed(db, draft={"target_summary": "x", "risk_level": "low", "steps": [
        {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon",
         "tier": "passive_no_target_contact", "config": {"target": "acme.com"}},
    ]}, status="draft")
    svc = WorkflowService(db)
    with pytest.raises(HTTPException) as ei:
        await svc.approve(session_id=s.id, user=_user())
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_reject_terminal(db):
    s = await _seed(db, draft={"target_summary": "x", "risk_level": "low", "steps": [
        {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon",
         "tier": "passive_no_target_contact", "config": {"target": "acme.com"}},
    ]})
    user = _user()
    svc = WorkflowService(db)
    updated = await svc.reject(session_id=s.id, user=user)
    assert updated.status == "rejected"
