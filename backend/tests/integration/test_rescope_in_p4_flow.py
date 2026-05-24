"""Rescope integration with v4.0 P4 flow.

Verifies that the existing `RescopeService.request_rescope` state machine
(v3.2.1 §5) still triggers correctly when the new Performer dispatcher
discovers an out-of-scope target. The rescope contract is unchanged —
P4 reuses it without redesign.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.project import Project
from app.models.session import PentestSession, RescopeApproval
from app.models.user import Team, User, UserRole


async def _seed_session_running(db) -> PentestSession:
    team = Team(name=f"t-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@x.com",
        password_hash="x" * 60,
        full_name="u",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()
    project = Project(name="p", client_name="acme", status="active", created_by=user.id)
    db.add(project)
    await db.flush()
    session_row = PentestSession(
        project_id=project.id,
        prompt="recon",
        status="running",
        interview_state="approved",
        ambiguity_score=Decimal("0.1"),
    )
    db.add(session_row)
    await db.flush()
    return session_row


@pytest.mark.asyncio
async def test_rescope_approval_round_trip(db):
    """RescopeApproval row can be created with `pending` status, decided
    `accepted`, and retrieved with `accepted_targets` populated."""
    from sqlalchemy import select

    session = await _seed_session_running(db)

    approval = RescopeApproval(
        pentest_session_id=session.id,
        requested_at=datetime.now(timezone.utc),
        discovered_targets={"ip_ranges": ["192.168.50.0/24"]},
        requesting_step_id="nmap-recon-1",
        status="pending",
    )
    db.add(approval)
    await db.flush()

    fetched = (
        await db.execute(
            select(RescopeApproval).where(RescopeApproval.id == approval.id)
        )
    ).scalar_one()
    assert fetched.status == "pending"
    assert fetched.discovered_targets["ip_ranges"] == ["192.168.50.0/24"]

    # Operator accepts.
    fetched.status = "accepted"
    fetched.accepted_targets = fetched.discovered_targets
    fetched.decided_at = datetime.now(timezone.utc)
    fetched.decision_reason = "in scope per SoW"
    await db.flush()

    re_fetched = (
        await db.execute(
            select(RescopeApproval).where(RescopeApproval.id == approval.id)
        )
    ).scalar_one()
    assert re_fetched.status == "accepted"
    assert re_fetched.accepted_targets is not None
    assert re_fetched.decided_at is not None


@pytest.mark.asyncio
async def test_session_paused_for_rescope_state(db):
    """Session can transition into `paused_for_rescope` by setting the
    timestamp + state. Existing v3.2.1 columns are reused by P4."""
    from sqlalchemy import select

    session = await _seed_session_running(db)
    session.status = "paused_for_rescope"
    session.paused_for_rescope_at = datetime.now(timezone.utc)
    session.rescope_request_json = {
        "discovered_targets": {"domains": ["new.example.com"]}
    }
    await db.flush()

    fetched = (
        await db.execute(
            select(PentestSession).where(PentestSession.id == session.id)
        )
    ).scalar_one()
    assert fetched.status == "paused_for_rescope"
    assert fetched.paused_for_rescope_at is not None
    assert fetched.rescope_request_json["discovered_targets"]["domains"] == [
        "new.example.com"
    ]
