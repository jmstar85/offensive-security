"""Performer MsgChain persistence (Increment C).

``Performer.run_session`` must persist one ``MsgChain`` row per role it runs so
the Agents panel can replay (GET on mount) and light up live (refetch on a
``topic="agents"`` event). The row is created ``running`` BEFORE the role runs
and finalized (``finished`` / ``failed``) AFTER — each write committed on the
shared session and announced with a ``msgchain_updated`` agents event.

This drives the real ``run_session`` loop over the seeded Generator → Pentester
→ Reporter smoke roles (no live LLM needed) with a lightweight fake db that
assigns primary keys on flush, then asserts both the persisted rows and the
emitted event stream.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# Importing `seed` is the only thing that populates ROLE_REGISTRY in tests.
from app.orchestrator.roles import seed as _seed  # noqa: F401  (side-effect)
from app.orchestrator.roles.registry import get_role
from app.core.events import event_bus
from app.models.msgchain import MsgChain
from app.orchestrator.performer import Performer


def _fake_db() -> tuple[AsyncMock, list, list]:
    """An AsyncMock db that records added rows / executed statements and assigns
    a primary key on flush (SQLAlchemy would do this against a real engine)."""
    added: list = []
    executed: list = []

    db = AsyncMock()
    db.add = MagicMock(side_effect=added.append)

    async def _flush(*_a, **_k):
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def _execute(stmt, *_a, **_k):
        executed.append(stmt)
        return MagicMock()

    db.flush = AsyncMock(side_effect=_flush)
    db.execute = AsyncMock(side_effect=_execute)
    return db, added, executed


@pytest.mark.asyncio
async def test_run_session_persists_one_msgchain_per_role():
    db, added, executed = _fake_db()
    sid = uuid.uuid4()
    performer = Performer(db=db, session_id=sid)

    performer.register_role(get_role("generator")())
    performer.register_role(get_role("pentester")())
    performer.register_role(get_role("reporter")())

    # Subscribe to the Agents panel topic BEFORE the run so we capture the
    # msgchain_updated stream in order.
    queue = event_bus.subscribe(str(sid), topics={"agents"})
    try:
        await performer.run_session()
    finally:
        event_bus.unsubscribe(str(sid), queue)

    # One MsgChain row created per role, in topological order, each `running`.
    chains = [o for o in added if isinstance(o, MsgChain)]
    assert [c.role_name for c in chains] == ["generator", "pentester", "reporter"]
    assert all(c.status == "running" for c in chains)
    assert all(c.messages_json == [] for c in chains)

    # One finalize UPDATE per role (end-persist).
    assert len(executed) == 3

    # Committed at every write so the separate-session GET sees rows live:
    # 3 starts + 3 finalizes = 6 commits.
    assert db.commit.await_count == 6

    # Agents event stream: running → finished for each role, in order.
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    msgchain_events = [
        (e["role"], e["status"])
        for e in events
        if e.get("type") == "msgchain_updated"
    ]
    assert msgchain_events == [
        ("generator", "running"),
        ("generator", "finished"),
        ("pentester", "running"),
        ("pentester", "finished"),
        ("reporter", "running"),
        ("reporter", "finished"),
    ]


@pytest.mark.asyncio
async def test_msgchain_persistence_failure_does_not_break_run():
    """Observability must never crash the role loop: if the start-persist flush
    raises, the run still completes and no finalize UPDATE is attempted."""
    db, added, executed = _fake_db()

    async def _boom(*_a, **_k):
        raise RuntimeError("db down")

    db.flush = AsyncMock(side_effect=_boom)

    sid = uuid.uuid4()
    performer = Performer(db=db, session_id=sid)
    performer.register_role(get_role("generator")())
    performer.register_role(get_role("reporter")())

    results = await performer.run_session()

    # Loop ran to completion despite persistence failing.
    assert [r.role_name for r in results] == ["generator", "reporter"]
    # start-persist failed → chain_id is None → no finalize UPDATE issued.
    assert executed == []
