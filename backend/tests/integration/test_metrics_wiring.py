"""Plan v3.2.1 §6 — service-level metric emission.

Verifies that WorkflowService.send_message and RescopeService.pause_for_rescope /
decide_rescope / expire_stale_pending emit the expected counters.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.user import UserRole
from app.observability.metrics import metrics
from app.orchestrator.model_client import Response
from app.orchestrator.rescope_service import DiscoveredTarget, RescopeService
from app.orchestrator.workflow_service import WorkflowService


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        role=UserRole.MEMBER,
        team_id=uuid.uuid4(),
    )


async def _project_with_whitelist(db, whitelist_rules):
    from app.models.project import Project, Target
    p = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(p)
    await db.flush()
    db.add(Target(
        project_id=p.id,
        ip_ranges=["10.0.0.0/24"],
        domains=["acme.com"],
        whitelist_rules=whitelist_rules,
    ))
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_send_message_emits_turn_and_token_metrics(db, monkeypatch):
    # Legacy v3.2.1 chat path (PR10 flipped osa_flow_ui_enabled default ON).
    from app.core.config import settings
    monkeypatch.setattr(settings, "osa_flow_ui_enabled", False)
    project = await _project_with_whitelist(db, {"passive_allowed": ["acme.com"]})
    user = _user()
    mock = AsyncMock()
    mock.send = AsyncMock(return_value=Response(
        text=json.dumps({
            "ambiguity": 0.2,
            "blockers": [],
            "reasoning": "ok",
            "draft_plan": {"target_summary": "t", "risk_level": "low", "steps": [
                {"order": 1, "agent": "passive_recon", "action": "passive_dns_recon", "tier": "passive_no_target_contact"}
            ]},
        }),
        tokens_in=100, tokens_out=50, raw=None,
    ))

    before_turns = metrics.session_interview_turns_total.value(outcome="ready_for_review")
    before_tokens_in = metrics.anthropic_tokens_total.value(model="claude-sonnet-4-6", phase="input")
    before_tokens_out = metrics.anthropic_tokens_total.value(model="claude-sonnet-4-6", phase="output")
    before_ambig = metrics.session_ambiguity_score.value(bucket="0.2-0.4")

    svc = WorkflowService(db, model_client=mock)
    s = await svc.create_draft(project_id=project.id, initial_prompt="x", user=user)
    await svc.send_message(session_id=s.id, user_message="hi", user=user)

    assert metrics.session_interview_turns_total.value(outcome="ready_for_review") - before_turns == 1
    assert metrics.anthropic_tokens_total.value(model="claude-sonnet-4-6", phase="input") - before_tokens_in == 100
    assert metrics.anthropic_tokens_total.value(model="claude-sonnet-4-6", phase="output") - before_tokens_out == 50
    assert metrics.session_ambiguity_score.value(bucket="0.2-0.4") - before_ambig == 1


@pytest.mark.asyncio
async def test_pause_for_rescope_emits_rescope_paused_metric(db):
    from app.models.project import Project, Target
    from app.models.session import PentestSession
    project = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(project)
    await db.flush()
    db.add(Target(project_id=project.id, ip_ranges=[], domains=["acme.com"],
                  whitelist_rules={"active_allowed": ["acme.com"]}))
    s = PentestSession(
        project_id=project.id, prompt="x", status="executing",
        interview_state="ready_for_review", interview_turn_count=2,
        ambiguity_score=Decimal("0.200"), model_id="claude-sonnet-4-6",
        draft_plan_json={"target_summary": "x", "risk_level": "low", "steps": []},
    )
    db.add(s)
    await db.flush()

    before_paused = metrics.rescope_events_total.value(action="paused")
    before_needs = metrics.active_recon_targets_total.value(result="needs_rescope")

    rs = RescopeService(db)
    await rs.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    assert metrics.rescope_events_total.value(action="paused") - before_paused == 1
    assert metrics.active_recon_targets_total.value(result="needs_rescope") - before_needs == 1


@pytest.mark.asyncio
async def test_decide_rescope_emits_approved_or_rejected_metric(db):
    from app.models.project import Project, Target
    from app.models.session import PentestSession
    project = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(project)
    await db.flush()
    db.add(Target(project_id=project.id, ip_ranges=[], domains=["acme.com"],
                  whitelist_rules={"active_allowed": ["acme.com"]}))
    s = PentestSession(
        project_id=project.id, prompt="x", status="executing",
        interview_state="ready_for_review", interview_turn_count=2,
        ambiguity_score=Decimal("0.200"), model_id="claude-sonnet-4-6",
        draft_plan_json={"target_summary": "x", "risk_level": "low", "steps": []},
    )
    db.add(s)
    await db.flush()

    rs = RescopeService(db)
    approval = await rs.pause_for_rescope(
        session_id=s.id,
        discovered=[DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1")],
        requesting_step_id="step-1",
    )

    before_rejected = metrics.rescope_events_total.value(action="rejected")
    await rs.decide_rescope(
        session_id=s.id, rescope_id=approval.id,
        accept=[], reject=["evil.org"], user=_user(),
    )
    assert metrics.rescope_events_total.value(action="rejected") - before_rejected == 1


@pytest.mark.asyncio
async def test_expire_stale_pending_emits_auto_drop_metric(db):
    from app.models.project import Project, Target
    from app.models.session import PentestSession
    project = Project(name="p", client_name="acme", created_by=uuid.uuid4(), status="active")
    db.add(project)
    await db.flush()
    db.add(Target(project_id=project.id, ip_ranges=[], domains=["acme.com"],
                  whitelist_rules={"active_allowed": ["acme.com"]}))
    s = PentestSession(
        project_id=project.id, prompt="x", status="executing",
        interview_state="ready_for_review", interview_turn_count=2,
        ambiguity_score=Decimal("0.200"), model_id="claude-sonnet-4-6",
        draft_plan_json={"target_summary": "x", "risk_level": "low", "steps": []},
    )
    db.add(s)
    await db.flush()

    rs = RescopeService(db)
    approval = await rs.pause_for_rescope(
        session_id=s.id,
        discovered=[DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1")],
        requesting_step_id="step-1",
    )
    approval.requested_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.flush()

    before_drop = metrics.rescope_events_total.value(action="auto_drop")
    await rs.expire_stale_pending()
    assert metrics.rescope_events_total.value(action="auto_drop") - before_drop == 1
