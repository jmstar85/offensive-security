"""Plan v3.2.1 §5.1 — rescope state machine end-to-end (Critic D-1 BLOCKER).

Covers:
  - validate_discovered_targets classifies hosts by tier
  - pause_for_rescope writes a pending row + transitions session
  - decide_rescope accept/reject must partition the discovered set
  - resume on accept, kill on full reject
  - timeout janitor auto-drops pending rows (safety-favoring)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.user import UserRole
from app.orchestrator.rescope_service import (
    DiscoveredTarget,
    RescopeService,
)


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        role=UserRole.MEMBER,
        team_id=uuid.uuid4(),
    )


async def _seed(db, whitelist_rules):
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
        whitelist_rules=whitelist_rules,
    ))
    s = PentestSession(
        project_id=project.id,
        prompt="x",
        status="executing",
        interview_state="ready_for_review",
        interview_turn_count=4,
        ambiguity_score=Decimal("0.200"),
        model_id="claude-sonnet-4-6",
        draft_plan_json={"target_summary": "x", "risk_level": "low", "steps": []},
    )
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_validate_discovered_targets_classifies_by_tier(db):
    s = await _seed(db, {
        "passive_allowed": ["acme.com"],
        "active_allowed": ["beta.acme.com"],
    })
    svc = RescopeService(db)
    res = await svc.validate_discovered_targets(
        session_id=s.id,
        targets=[
            DiscoveredTarget(host="api.acme.com", tier="passive_low_touch", discovered_by_step_id="step-1"),
            DiscoveredTarget(host="api.acme.com", tier="active_recon", discovered_by_step_id="step-1"),
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
    )
    # api.acme.com passes passive (subdomain match) but fails active (not in active_allowed)
    assert "api.acme.com" in res.accepted   # the passive entry
    assert "api.acme.com" in res.rejected   # the active entry
    assert "evil.org" in res.rejected


@pytest.mark.asyncio
async def test_wildcard_block_routes_to_blocked_not_pending(db):
    s = await _seed(db, {
        "active_allowed": ["acme.com"],
        "wildcard_block_regex": [r"^internal\..*"],
    })
    svc = RescopeService(db)
    discovered = [
        DiscoveredTarget(host="internal.acme.com", tier="active_recon", discovered_by_step_id="step-1"),
        DiscoveredTarget(host="public.acme.com", tier="active_recon", discovered_by_step_id="step-1"),
    ]
    v = await svc.validate_discovered_targets(session_id=s.id, targets=discovered)
    assert v.blocked_by_wildcard == ["internal.acme.com"]
    assert v.accepted == ["public.acme.com"]
    assert v.rejected == []


@pytest.mark.asyncio
async def test_pause_for_rescope_creates_row_and_transitions_session(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    assert approval is not None
    assert approval.status == "pending"
    assert "evil.org" in approval.discovered_targets["rejected"]

    await db.refresh(s)
    assert s.status == "paused_for_rescope"
    assert s.paused_for_rescope_at is not None


@pytest.mark.asyncio
async def test_pause_for_rescope_skipped_when_no_rejected_targets(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    result = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="api.acme.com", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    assert result is None
    await db.refresh(s)
    assert s.status == "executing"


@pytest.mark.asyncio
async def test_decide_rescope_accept_resumes_session(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="newhost.example", tier="active_recon", discovered_by_step_id="step-1"),
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    decision = await svc.decide_rescope(
        session_id=s.id,
        rescope_id=approval.id,
        accept=["newhost.example"],
        reject=["evil.org"],
        user=_user(),
        reason="operator added newhost to engagement",
    )
    assert decision.session_status == "executing"
    assert decision.accepted_targets == ["newhost.example"]
    await db.refresh(s)
    assert s.status == "executing"
    assert s.rescope_request_json is None


@pytest.mark.asyncio
async def test_decide_rescope_full_reject_kills_session(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    decision = await svc.decide_rescope(
        session_id=s.id,
        rescope_id=approval.id,
        accept=[],
        reject=["evil.org"],
        user=_user(),
        reason="not in engagement scope",
    )
    assert decision.session_status == "killed"
    await db.refresh(s)
    assert s.status == "killed"
    assert s.ended_at is not None


@pytest.mark.asyncio
async def test_decide_rescope_requires_partition(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[
            DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1"),
            DiscoveredTarget(host="other.org", tier="active_recon", discovered_by_step_id="step-1"),
        ],
        requesting_step_id="step-1",
    )
    with pytest.raises(HTTPException) as ei:
        await svc.decide_rescope(
            session_id=s.id,
            rescope_id=approval.id,
            accept=["evil.org"],
            reject=[],  # missing other.org
            user=_user(),
        )
    assert ei.value.status_code == 400
    assert ei.value.detail["error"] == "accept_reject_must_partition_discovered"


@pytest.mark.asyncio
async def test_decide_rescope_rejects_when_already_decided(db):
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1")],
        requesting_step_id="step-1",
    )
    user = _user()
    await svc.decide_rescope(
        session_id=s.id, rescope_id=approval.id,
        accept=[], reject=["evil.org"], user=user,
    )
    # second decision must fail
    with pytest.raises(HTTPException) as ei:
        await svc.decide_rescope(
            session_id=s.id, rescope_id=approval.id,
            accept=["evil.org"], reject=[], user=user,
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_timeout_janitor_auto_drops_stale_pending(db):
    """Auto-drop is safety-favoring: pending → timed_out with rejected=discovered."""
    s = await _seed(db, {"active_allowed": ["acme.com"]})
    svc = RescopeService(db)
    approval = await svc.pause_for_rescope(
        session_id=s.id,
        discovered=[DiscoveredTarget(host="evil.org", tier="active_recon", discovered_by_step_id="step-1")],
        requesting_step_id="step-1",
    )
    # Backdate the request to force a timeout.
    approval.requested_at = datetime.now(timezone.utc) - timedelta(seconds=3600)
    await db.flush()

    expired = await svc.expire_stale_pending()
    assert approval.id in expired

    await db.refresh(approval)
    assert approval.status == "timed_out"
    assert approval.accepted_targets == []
    assert "evil.org" in approval.rejected_targets

    await db.refresh(s)
    # No accept anywhere → killed by safety-favoring resume_or_kill
    assert s.status == "killed"
