"""GET /pentest-sessions/{id}/msgchains tests (v4.0 P3-main).

Backend slice of the Agents tab — verifies the list endpoint returns role
chains in start-time order with the metadata the UI needs (role_name,
status, retries, message_count). The endpoint stays minimal: no message
body returned (drilling into individual messages is v3.4).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.api.v1.pentest_sessions import list_msgchains
from app.models.msgchain import MsgChain
from app.models.project import Project
from app.models.session import PentestSession
from app.models.user import Team, User, UserRole


async def _seed_session_with_chains(db) -> tuple[uuid.UUID, list[uuid.UUID]]:
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
        name="proj", client_name="acme", status="active", created_by=user.id
    )
    db.add(project)
    await db.flush()
    session_row = PentestSession(
        project_id=project.id, prompt="x", status="running"
    )
    db.add(session_row)
    await db.flush()

    now = datetime.now(timezone.utc)
    chains = [
        MsgChain(
            pentest_session_id=session_row.id,
            role_name="generator",
            messages_json=[{"role": "user", "content": "scan"}],
            started_at=now,
            status="finished",
        ),
        MsgChain(
            pentest_session_id=session_row.id,
            role_name="pentester",
            messages_json=[
                {"role": "assistant", "content": "tool call 1"},
                {"role": "tool", "content": "result"},
            ],
            started_at=now,
            status="running",
            retries=1,
        ),
        MsgChain(
            pentest_session_id=session_row.id,
            role_name="memorist",
            messages_json=[],
            started_at=now,
            status="created",
        ),
    ]
    db.add_all(chains)
    await db.flush()
    return session_row.id, [c.id for c in chains]


@pytest.mark.asyncio
async def test_list_msgchains_returns_rows_in_start_order(db):
    session_id, chain_ids = await _seed_session_with_chains(db)

    user = User(
        email=f"caller-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Caller",
        role=UserRole.MEMBER,
        team_id=uuid.uuid4(),
    )

    rows = await list_msgchains(
        session_id=session_id,
        db=db,
        current_user=user,
    )

    assert len(rows) == 3
    role_names = [r.role_name for r in rows]
    assert role_names == ["generator", "pentester", "memorist"]


@pytest.mark.asyncio
async def test_list_msgchains_carries_message_count(db):
    """The endpoint surfaces `message_count` without returning message bodies."""
    session_id, _ = await _seed_session_with_chains(db)

    user = User(
        email=f"caller-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Caller",
        role=UserRole.MEMBER,
        team_id=uuid.uuid4(),
    )

    rows = await list_msgchains(session_id=session_id, db=db, current_user=user)

    counts = {r.role_name: r.message_count for r in rows}
    assert counts == {"generator": 1, "pentester": 2, "memorist": 0}


@pytest.mark.asyncio
async def test_list_msgchains_surfaces_retries_and_status(db):
    session_id, _ = await _seed_session_with_chains(db)
    user = User(
        email=f"caller-{uuid.uuid4()}@example.com",
        password_hash="x" * 60,
        full_name="Caller",
        role=UserRole.MEMBER,
        team_id=uuid.uuid4(),
    )

    rows = await list_msgchains(session_id=session_id, db=db, current_user=user)
    pentester_row = next(r for r in rows if r.role_name == "pentester")
    assert pentester_row.retries == 1
    assert pentester_row.status == "running"
