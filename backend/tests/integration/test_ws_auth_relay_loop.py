"""Integration test for the WebSocket auth gate + topic-relay contract (PR1 / AC6).

Route under test: /api/v1/ws/sessions/{id}
  (backend/app/api/v1/ws.py, mounted in main.py under the /api/v1 prefix)

Why this lives in tests/integration/ (not tests/e2e/)
-----------------------------------------------------
It exercises the *in-process* WS auth function + event-bus relay; it needs no
live DVWA/Juice target. The tests/e2e/ folder is skip-gated behind OSA_E2E_*
env vars, so a WS contract test placed there would silently never run. This is
an in-process contract test, so it belongs here where it gates the PR1 fix.

Coverage
--------
A) `_authorize_session_access` — the real auth function rejects missing/invalid
   tokens with close-code 4001 before any DB access.
B) `session_ws` handler — driven through a fake WebSocket, the real handler
   closes with 4001 and never accepts when the token is missing/invalid.
C) Topic relay — the EventBus contract the handler depends on: a topic filter
   delivers only matching events; an unfiltered subscriber receives all. Run in
   a single event loop (asyncio_mode = "auto"), so no cross-loop flakiness.
D) `_parse_topics` — the seam the handler uses to turn the query param into the
   subscribe() filter.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

from app.api.v1.ws import (
    _authorize_session_access,
    _parse_topics,
    session_ws,
)
from app.core.events import EventBus


# ---------------------------------------------------------------------------
# A) _authorize_session_access — real auth function, DB-free rejection paths
# ---------------------------------------------------------------------------

async def test_authorize_rejects_missing_token():
    ok, code = await _authorize_session_access(None, uuid.uuid4())
    assert ok is False
    assert code == 4001


async def test_authorize_rejects_invalid_token():
    with patch("app.api.v1.ws.decode_access_token", return_value=None):
        ok, code = await _authorize_session_access("bad-token", uuid.uuid4())
    assert ok is False
    assert code == 4001


async def test_authorize_rejects_non_uuid_subject():
    with patch("app.api.v1.ws.decode_access_token", return_value="not-a-uuid"):
        ok, code = await _authorize_session_access("tok", uuid.uuid4())
    assert ok is False
    assert code == 4001


# ---------------------------------------------------------------------------
# B) session_ws handler — auth gate, via a minimal fake WebSocket
#
# Driving the real handler avoids both a live socket loop (flaky: cross-event-
# loop publish) and app lifespan/DB startup. Missing/invalid token short-
# circuits in _authorize_session_access before any DB access, so the handler
# must close(4001) and never accept().
# ---------------------------------------------------------------------------

class _FakeWebSocket:
    def __init__(self, query_params: dict[str, str]) -> None:
        self.query_params = query_params
        self.accepted = False
        self.close_code: int | None = None
        self.sent: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


async def test_handler_closes_4001_on_missing_token():
    ws = _FakeWebSocket(query_params={})
    await session_ws(ws, uuid.uuid4())  # type: ignore[arg-type]
    assert ws.accepted is False
    assert ws.close_code == 4001


async def test_handler_closes_4001_on_invalid_token():
    ws = _FakeWebSocket(query_params={"token": "bad"})
    with patch("app.api.v1.ws.decode_access_token", return_value=None):
        await session_ws(ws, uuid.uuid4())  # type: ignore[arg-type]
    assert ws.accepted is False
    assert ws.close_code == 4001


# ---------------------------------------------------------------------------
# C) Topic-relay contract the WS handler relies on (event_bus.subscribe filter)
#
# Fresh EventBus per test → isolated; single event loop → no cross-loop issue.
# ---------------------------------------------------------------------------

async def test_relay_delivers_matching_topic():
    bus = EventBus()
    sid = str(uuid.uuid4())
    q = bus.subscribe(sid, topics={"tasks"})
    await bus.publish(sid, {"type": "task_update", "msg": "hello"}, topic="tasks")
    event = q.get_nowait()
    assert event["type"] == "task_update"
    assert event["msg"] == "hello"


async def test_relay_drops_non_matching_topic():
    bus = EventBus()
    sid = str(uuid.uuid4())
    q = bus.subscribe(sid, topics={"tasks"})
    # Off-topic publish must NOT enqueue for a tasks-only subscriber.
    await bus.publish(sid, {"type": "terminal_line"}, topic="terminal")
    assert q.empty()
    # A matching publish still arrives.
    await bus.publish(sid, {"type": "task_done"}, topic="tasks")
    assert q.get_nowait()["type"] == "task_done"


async def test_relay_unfiltered_receives_all_topics():
    bus = EventBus()
    sid = str(uuid.uuid4())
    q = bus.subscribe(sid, topics=None)  # legacy unfiltered stream
    await bus.publish(sid, {"type": "from_terminal"}, topic="terminal")
    await bus.publish(sid, {"type": "from_tasks"}, topic="tasks")
    got = {q.get_nowait()["type"], q.get_nowait()["type"]}
    assert got == {"from_terminal", "from_tasks"}


async def test_relay_unsubscribe_is_clean():
    bus = EventBus()
    sid = str(uuid.uuid4())
    q = bus.subscribe(sid, topics={"tasks"})
    assert bus._subscriber_count(sid) == 1
    bus.unsubscribe(sid, q)
    assert bus._subscriber_count(sid) == 0


# ---------------------------------------------------------------------------
# D) _parse_topics — the seam the handler uses to build the subscribe() filter
# ---------------------------------------------------------------------------

def test_parse_topics_none_for_missing_param():
    assert _parse_topics(None) is None
    assert _parse_topics("") is None


def test_parse_topics_multi_with_whitespace_and_dups():
    assert _parse_topics("tasks , terminal, tasks") == {"tasks", "terminal"}
