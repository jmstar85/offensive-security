"""Flow Terminal + Tasks REPLAY-on-reload (migration 013).

Backend slice of the /flow reload path: the Terminal + Tasks panels already work
LIVE off the WS ``terminal`` / ``tasks`` topics; migration 013 persists the same
data so a page reload REPLAYS it. This covers:

- ``TerminalLine`` round-trips and reads back ordered by the per-session ``seq``.
- ``TerminalLineSink`` assigns a DB-derived monotonic ``seq`` (continuing across
  fresh sink instances), buffers, auto-flushes at the threshold, and commits.
- ``GET /{id}/terminal?after_seq=`` returns lines with ``seq > after_seq`` ordered,
  gated by team-ownership authz (same-team OK, wrong-team 403, admin bypass).
- ``step_order`` persists on ``AgentExecution`` and is surfaced by ``/executions``.

Route functions are called directly (mirroring ``test_msgchains_endpoint.py`` /
``test_pentest_messages_history.py``); the sink test uses a dedicated committing
session because the shared ``db`` fixture runs inside an outer ``session.begin()``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.sessions import get_executions, get_terminal
from app.models.project import Project
from app.models.session import AgentExecution, PentestSession, TerminalLine
from app.models.user import UserRole
from app.orchestrator.terminal_sink import TerminalLineSink


def _user(team_id: uuid.UUID, role=UserRole.MEMBER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="op@example.com",
        full_name="Op",
        role=role,
        is_active=True,
        team_id=team_id,
    )


async def _seed_session(db, *, team_id: uuid.UUID) -> uuid.UUID:
    """Seed project + session (team_id set as WorkflowService.create_draft does)."""
    project = Project(
        name="proj", client_name="acme", status="active", created_by=uuid.uuid4()
    )
    db.add(project)
    await db.flush()
    session_row = PentestSession(
        project_id=project.id, prompt="x", status="running", team_id=team_id
    )
    db.add(session_row)
    await db.flush()
    return session_row.id


# ── Model round-trip ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_line_round_trips_ordered_by_seq(db):
    team_id = uuid.uuid4()
    session_id = await _seed_session(db, team_id=team_id)

    # Insert out of seq order; the read must come back ordered by seq.
    for seq, line in [(3, "third"), (1, "first"), (2, "second")]:
        db.add(
            TerminalLine(
                session_id=session_id,
                execution_id=None,
                seq=seq,
                agent_type="nmap",
                line=line,
            )
        )
    await db.flush()

    rows = (
        await db.execute(
            select(TerminalLine)
            .where(TerminalLine.session_id == session_id)
            .order_by(TerminalLine.seq)
        )
    ).scalars().all()

    assert [r.seq for r in rows] == [1, 2, 3]
    assert [r.line for r in rows] == ["first", "second", "third"]
    assert rows[0].created_at is not None  # server_default now() populated on flush


# ── TerminalLineSink: DB-derived monotonic seq + buffering ───────────────────


@pytest.mark.asyncio
async def test_sink_assigns_monotonic_seq_across_instances(db):
    """Two fresh sinks on the SAME session (the within-run "one sink per step"
    case) keep seq monotonic because each seeds from ``max(seq)`` — sink2 sees
    sink1's flushed rows on the shared session, so seq continues 4,5. The sink
    flushes (no commit); the caller commits at its phase boundaries."""
    session_id = uuid.uuid4()

    sink1 = TerminalLineSink(db, session_id)
    seqs1 = [
        await sink1.add(execution_id=None, agent_type="nmap", line=f"a{i}")
        for i in range(3)
    ]
    await sink1.flush()

    sink2 = TerminalLineSink(db, session_id)
    seqs2 = [
        await sink2.add(execution_id=None, agent_type="nmap", line=f"b{i}")
        for i in range(2)
    ]
    await sink2.flush()

    assert seqs1 == [1, 2, 3]
    assert seqs2 == [4, 5]  # seeded from the shared-session max(seq)=3

    rows = (
        await db.execute(
            select(TerminalLine)
            .where(TerminalLine.session_id == session_id)
            .order_by(TerminalLine.seq)
        )
    ).scalars().all()
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert [r.line for r in rows] == ["a0", "a1", "a2", "b0", "b1"]


@pytest.mark.asyncio
async def test_sink_auto_flushes_at_threshold(db):
    """Buffering FLUSH_THRESHOLD lines bulk-inserts them without an explicit
    flush() call, so the tail never grows unbounded under load."""
    session_id = uuid.uuid4()

    sink = TerminalLineSink(db, session_id)
    for i in range(TerminalLineSink.FLUSH_THRESHOLD):
        await sink.add(execution_id=None, agent_type="nmap", line=f"L{i}")
    # No explicit flush() yet — the threshold add() already flushed the batch.

    count = len(
        (
            await db.execute(
                select(TerminalLine).where(TerminalLine.session_id == session_id)
            )
        ).scalars().all()
    )
    assert count == TerminalLineSink.FLUSH_THRESHOLD


# ── GET /{id}/terminal endpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_terminal_returns_lines_after_seq_ordered(db):
    team_id = uuid.uuid4()
    session_id = await _seed_session(db, team_id=team_id)
    for seq in (1, 2, 3, 4, 5):
        db.add(
            TerminalLine(
                session_id=session_id, execution_id=None, seq=seq,
                agent_type="nmap", line=f"line-{seq}",
            )
        )
    await db.flush()

    rows = await get_terminal(
        session_id=session_id, after_seq=2, db=db, current_user=_user(team_id)
    )

    assert [r.seq for r in rows] == [3, 4, 5]
    assert [r.line for r in rows] == ["line-3", "line-4", "line-5"]

    # after_seq default 0 → the full history.
    all_rows = await get_terminal(
        session_id=session_id, after_seq=0, db=db, current_user=_user(team_id)
    )
    assert [r.seq for r in all_rows] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_get_terminal_forbids_other_team(db):
    session_id = await _seed_session(db, team_id=uuid.uuid4())
    other = _user(uuid.uuid4())  # different team

    with pytest.raises(HTTPException) as ei:
        await get_terminal(
            session_id=session_id, after_seq=0, db=db, current_user=other
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_get_terminal_admin_bypasses_team_check(db):
    team_id = uuid.uuid4()
    session_id = await _seed_session(db, team_id=team_id)
    db.add(
        TerminalLine(
            session_id=session_id, execution_id=None, seq=1,
            agent_type="nmap", line="hello",
        )
    )
    await db.flush()

    admin = _user(uuid.uuid4(), role=UserRole.ADMIN)  # different team, still allowed
    rows = await get_terminal(
        session_id=session_id, after_seq=0, db=db, current_user=admin
    )
    assert [r.line for r in rows] == ["hello"]


@pytest.mark.asyncio
async def test_get_terminal_unknown_session_404(db):
    with pytest.raises(HTTPException) as ei:
        await get_terminal(
            session_id=uuid.uuid4(), after_seq=0, db=db,
            current_user=_user(uuid.uuid4()),
        )
    assert ei.value.status_code == 404


# ── step_order persists + surfaced by /executions ────────────────────────────


@pytest.mark.asyncio
async def test_step_order_persists_and_returned_by_executions(db):
    team_id = uuid.uuid4()
    session_id = await _seed_session(db, team_id=team_id)
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            AgentExecution(
                session_id=session_id, agent_type="nmap", status="completed",
                step_order=1, started_at=now,
            ),
            AgentExecution(
                session_id=session_id, agent_type="nuclei", status="running",
                step_order=2, started_at=now,
            ),
            AgentExecution(
                session_id=session_id, agent_type="legacy", status="completed",
                step_order=None, started_at=now,
            ),
        ]
    )
    await db.flush()

    rows = await get_executions(
        session_id=session_id, db=db, current_user=_user(team_id)
    )

    by_agent = {r.agent_type: r for r in rows}
    assert by_agent["nmap"].step_order == 1
    assert by_agent["nuclei"].step_order == 2
    assert by_agent["legacy"].step_order is None
    # status still surfaced (Tasks panel overlays status by step_order on reload).
    assert by_agent["nuclei"].status == "running"
