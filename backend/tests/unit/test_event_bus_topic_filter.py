"""EventBus topic filter tests (v4.0 P3-spike, ADR-001).

Verifies the topic-filter contract on `EventBus.publish` / `subscribe`:
- A subscriber with `topics=None` receives every event regardless of topic
  (v2.1 backward compatibility).
- A subscriber with a non-empty filter receives only matching events.
- An event published with the default topic `"session"` reaches every legacy
  subscriber unchanged.
- `unsubscribe` cleans up the subscriber list with no leak.
"""
from __future__ import annotations


import pytest

from app.core.events import EventBus


@pytest.mark.asyncio
async def test_unfiltered_subscriber_receives_all_topics():
    """v2.1 backward compat: no topic filter means receive everything."""
    bus = EventBus()
    q = bus.subscribe("s1")  # no topics → receives all
    await bus.publish("s1", {"id": 1}, topic="terminal")
    await bus.publish("s1", {"id": 2}, topic="tasks")
    await bus.publish("s1", {"id": 3})  # default topic="session"

    received = [await q.get() for _ in range(3)]
    assert [e["id"] for e in received] == [1, 2, 3]


@pytest.mark.asyncio
async def test_topic_filter_excludes_non_matching():
    """A subscriber filtered to `terminal` does not see `tasks` events."""
    bus = EventBus()
    q = bus.subscribe("s1", topics={"terminal"})
    await bus.publish("s1", {"id": 1}, topic="terminal")
    await bus.publish("s1", {"id": 2}, topic="tasks")  # filtered out
    await bus.publish("s1", {"id": 3}, topic="terminal")

    received = [await q.get() for _ in range(2)]
    assert [e["id"] for e in received] == [1, 3]
    # Queue should be empty now — no third event leaked through.
    assert q.empty()


@pytest.mark.asyncio
async def test_multi_topic_filter_receives_each():
    """`topics={'terminal', 'tasks'}` receives both but excludes others."""
    bus = EventBus()
    q = bus.subscribe("s1", topics={"terminal", "tasks"})
    await bus.publish("s1", {"id": 1}, topic="terminal")
    await bus.publish("s1", {"id": 2}, topic="agents")  # excluded
    await bus.publish("s1", {"id": 3}, topic="tasks")

    received = [await q.get() for _ in range(2)]
    assert {e["id"] for e in received} == {1, 3}
    assert q.empty()


@pytest.mark.asyncio
async def test_default_publish_topic_is_session():
    """A subscriber filtered to `session` gets default-topic events."""
    bus = EventBus()
    q = bus.subscribe("s1", topics={"session"})
    await bus.publish("s1", {"id": 1})  # default topic
    await bus.publish("s1", {"id": 2}, topic="terminal")  # filtered

    received = await q.get()
    assert received["id"] == 1
    assert q.empty()


@pytest.mark.asyncio
async def test_topics_param_accepts_list_or_set():
    """The `topics` parameter accepts either a set or a list."""
    bus = EventBus()
    q_list = bus.subscribe("s1", topics=["terminal"])
    q_set = bus.subscribe("s1", topics={"terminal"})

    await bus.publish("s1", {"id": 1}, topic="terminal")

    assert (await q_list.get())["id"] == 1
    assert (await q_set.get())["id"] == 1


@pytest.mark.asyncio
async def test_unsubscribe_removes_subscriber_no_leak():
    """After unsubscribe the subscriber list shrinks and shows no leak."""
    bus = EventBus()
    assert bus._subscriber_count("s1") == 0

    q = bus.subscribe("s1", topics={"terminal"})
    assert bus._subscriber_count("s1") == 1

    bus.unsubscribe("s1", q)
    assert bus._subscriber_count("s1") == 0
    # Internal cleanup: empty session bucket should be removed.
    assert "s1" not in bus._subscribers


@pytest.mark.asyncio
async def test_queue_full_drops_subscriber(monkeypatch):
    """When a subscriber's queue is full, the publish drops them quietly
    (v2.1 drop-event semantics carried forward)."""
    bus = EventBus()
    q = bus.subscribe("s1")
    # Fill the queue to maxsize=500.
    for i in range(500):
        q.put_nowait({"i": i})

    await bus.publish("s1", {"i": "overflow"}, topic="session")

    # Subscriber should be removed after the overflow attempt.
    assert bus._subscriber_count("s1") == 0
