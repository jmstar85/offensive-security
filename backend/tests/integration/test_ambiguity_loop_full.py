"""AmbiguityLoop integration test (v4.0 P4)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.orchestrator.ambiguity_loop import AmbiguityLoop, _decide_next_state
from app.models.msgchain import MsgChain
from app.models.project import Project
from app.models.session import PentestSession, WorkflowMessage
from app.models.user import Team, User, UserRole


def test_decide_next_state_below_threshold_returns_ready():
    """Ambiguity ≤ threshold → ready_for_review regardless of turn count."""
    assert _decide_next_state(0.30, 1) == "ready_for_review"
    assert _decide_next_state(0.10, 5) == "ready_for_review"


def test_decide_next_state_above_threshold_under_max_keeps_interviewing():
    assert _decide_next_state(0.50, 1) == "interviewing"
    assert _decide_next_state(0.50, 5) == "interviewing"


def test_decide_next_state_above_threshold_at_max_needs_human_review():
    """At/over max_interview_turns + still ambiguous → needs_human_review."""
    from app.core.config import settings

    assert (
        _decide_next_state(0.50, settings.workflow_max_interview_turns)
        == "needs_human_review"
    )


async def _seed_session(db) -> PentestSession:
    team = Team(name=f"team-{uuid.uuid4()}")
    db.add(team)
    await db.flush()
    user = User(
        email=f"u-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Tester",
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
        prompt="scan the cluster",
        status="pending",
        interview_state="interviewing",
        interview_turn_count=0,
        ambiguity_score=Decimal("1.000"),
    )
    db.add(session_row)
    await db.flush()
    return session_row


@pytest.mark.asyncio
async def test_run_turn_persists_workflow_message_and_msgchain(db):
    """A single AmbiguityLoop turn writes one WorkflowMessage + one MsgChain."""
    from sqlalchemy import select

    session = await _seed_session(db)
    loop = AmbiguityLoop(db=db)
    result = await loop.run_turn(session, user_content="scan 10.0.0.0/24 for CVE-2024-xxx")

    msgs = (
        await db.execute(
            select(WorkflowMessage).where(WorkflowMessage.pentest_session_id == session.id)
        )
    ).scalars().all()
    assert len(msgs) == 1
    assert msgs[0].turn_index == 1

    chains = (
        await db.execute(
            select(MsgChain).where(MsgChain.pentest_session_id == session.id)
        )
    ).scalars().all()
    assert len(chains) == 1
    assert chains[0].role_name == "generator"
    assert chains[0].status == "finished"

    # Session state updated to whatever _decide_next_state returned.
    assert session.interview_turn_count == 1
    assert result.next_state in {"interviewing", "needs_human_review", "ready_for_review"}


@pytest.mark.asyncio
async def test_run_turn_envelope_parse_fallback(db):
    """If the envelope is unparseable, AmbiguityLoop returns a high-ambiguity
    fallback with `envelope_parse_failed` in blockers."""
    from app.orchestrator import ambiguity_loop as al

    parsed = al.AmbiguityLoop._parse_envelope("not-a-json-or-dict")
    assert parsed["ambiguity"] == 1.0
    assert "envelope_parse_failed" in parsed["blockers"]
