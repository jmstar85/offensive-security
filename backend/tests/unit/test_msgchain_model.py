"""MsgChain model round-trip + cascade tests (v4.0 P1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.msgchain import MsgChain
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole


async def _seed_session(db) -> PentestSession:
    """Build the team → user → project → pentest_session prerequisite chain."""
    team = Team(name=f"team-{uuid.uuid4()}")
    db.add(team)
    await db.flush()

    user = User(
        email=f"u-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Test User",
        role=UserRole.MEMBER,
        team_id=team.id,
    )
    db.add(user)
    await db.flush()

    project = Project(
        name="test-project",
        client_name="acme",
        status="active",
        created_by=user.id,
    )
    db.add(project)
    await db.flush()

    session_row = PentestSession(
        project_id=project.id,
        prompt="test prompt",
        status="pending",
    )
    db.add(session_row)
    await db.flush()
    return session_row


@pytest.mark.asyncio
async def test_msgchain_round_trip(db):
    """Insert + read + verify all columns of MsgChain."""
    session_row = await _seed_session(db)

    chain = MsgChain(
        pentest_session_id=session_row.id,
        role_name="generator",
        messages_json=[
            {"role": "user", "content": "scan example.com"},
            {"role": "assistant", "content": "OK", "usage": {"input_tokens": 12, "output_tokens": 3}},
        ],
        started_at=datetime.now(timezone.utc),
        status="running",
        retries=0,
    )
    db.add(chain)
    await db.flush()

    fetched = (await db.execute(select(MsgChain).where(MsgChain.id == chain.id))).scalar_one()
    assert fetched.role_name == "generator"
    assert fetched.status == "running"
    assert fetched.retries == 0
    assert len(fetched.messages_json) == 2
    assert fetched.messages_json[1]["usage"]["input_tokens"] == 12


@pytest.mark.asyncio
async def test_msgchain_cascade_delete_from_session(db):
    """Deleting a PentestSession cascades to its MsgChain rows."""
    session_row = await _seed_session(db)

    chain1 = MsgChain(pentest_session_id=session_row.id, role_name="pentester")
    chain2 = MsgChain(pentest_session_id=session_row.id, role_name="memorist")
    db.add_all([chain1, chain2])
    await db.flush()

    chain_ids = [chain1.id, chain2.id]

    # Use ORM cascade by deleting the session through the ORM. The
    # `msgchains` relationship has `cascade="all, delete-orphan"`.
    await db.delete(session_row)
    await db.flush()

    remaining = (
        await db.execute(select(MsgChain).where(MsgChain.id.in_(chain_ids)))
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_msgchain_default_messages_json_is_empty_list(db):
    """Inserting without messages_json should default to []."""
    session_row = await _seed_session(db)

    chain = MsgChain(pentest_session_id=session_row.id, role_name="adviser")
    db.add(chain)
    await db.flush()

    fetched = (await db.execute(select(MsgChain).where(MsgChain.id == chain.id))).scalar_one()
    assert fetched.messages_json == []
