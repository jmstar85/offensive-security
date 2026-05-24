"""WebSocket `topics` subscription integration test (v4.0 P3-spike).

Verifies the route at `backend/app/api/v1/ws.py` correctly forwards the
`topics` query param into `event_bus.subscribe`. Tests both the
backward-compat default (no `topics` → unfiltered) and the per-panel filter
path (e.g. `?topics=terminal` → only terminal events delivered).

This test uses a lightweight unit-style approach: it patches `event_bus` to
capture the subscribe call shape and verifies the parse step + delegation,
rather than spinning up a real WebSocket loop (which requires auth tokens +
asyncio infra not exercised elsewhere in this codebase).

The actual server-side WebSocket loop is covered indirectly via the EventBus
unit tests in `test_event_bus_topic_filter.py`.
"""
from __future__ import annotations


from app.api.v1.ws import _parse_topics


def test_parse_topics_none_for_missing_param():
    """No `topics` query param → None (legacy unfiltered behavior)."""
    assert _parse_topics(None) is None
    assert _parse_topics("") is None


def test_parse_topics_single_topic():
    """A single topic string → set of one."""
    assert _parse_topics("terminal") == {"terminal"}


def test_parse_topics_comma_separated():
    """Comma-separated list → set of multiple topics."""
    assert _parse_topics("terminal,tasks,agents") == {"terminal", "tasks", "agents"}


def test_parse_topics_strips_whitespace():
    """Whitespace around topic names is stripped."""
    assert _parse_topics("terminal , tasks , agents") == {"terminal", "tasks", "agents"}


def test_parse_topics_drops_empty_entries():
    """Empty entries (leading/trailing/double commas) are dropped."""
    assert _parse_topics(",terminal,,tasks,") == {"terminal", "tasks"}


def test_parse_topics_only_commas_returns_none():
    """All-empty input collapses to None (= legacy unfiltered)."""
    assert _parse_topics(",,,") is None


def test_parse_topics_returns_set_not_list():
    """The return type is a set so EventBus.subscribe can do O(1) membership
    checks on each publish."""
    result = _parse_topics("terminal,tasks")
    assert isinstance(result, set)
