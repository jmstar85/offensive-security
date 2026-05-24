"""Async event bus for orchestrator → WebSocket broadcasting.

v4.0 P3-spike (ADR-001 implementation):
- `publish(session_id, event, topic="session")` — accepts an optional topic
  string. Existing callers that omit `topic` default to `"session"`,
  preserving the v2.1 Monitor page behavior.
- `subscribe(session_id, topics=None)` — accepts an optional set/list of
  topics to filter on. `None` (default) receives all topics (legacy
  semantics). A non-empty filter delivers only matching events.

Backward compatibility: every v2.1 + P1 + P2a callsite continues to work
unchanged. New per-panel UI tabs (P3-main) pass a single-topic filter, e.g.
the Terminal tab opens with `topics={"terminal"}` and receives only the
terminal-log stream.

The 1:1 topic → UI-panel mapping is enumerated in
`.omc/research/pentagi-reference.md §4`.
"""
import asyncio
from collections import defaultdict
from typing import Any


# Subscriber record: a queue + an optional topic filter set.
# A None filter means "receive every topic" (v2.1-compatible default).
class _Subscriber:
    __slots__ = ("queue", "topics")

    def __init__(self, queue: asyncio.Queue, topics: set[str] | None) -> None:
        self.queue = queue
        self.topics = topics

    def matches(self, topic: str) -> bool:
        return self.topics is None or topic in self.topics


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[_Subscriber]] = defaultdict(list)

    def subscribe(
        self,
        session_id: str,
        topics: set[str] | list[str] | None = None,
    ) -> asyncio.Queue:
        """Subscribe to a session's event stream.

        `topics=None` (default) receives all events. A non-empty filter
        receives only events whose `topic` is in the set. Returns the
        underlying queue so the caller can `await queue.get()`.
        """
        topic_set: set[str] | None
        if topics is None:
            topic_set = None
        else:
            topic_set = set(topics) if not isinstance(topics, set) else topics

        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers[session_id].append(_Subscriber(queue, topic_set))
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber. No-op if the queue was already removed."""
        subs = self._subscribers.get(session_id)
        if not subs:
            return
        self._subscribers[session_id] = [s for s in subs if s.queue is not queue]
        if not self._subscribers[session_id]:
            # Avoid leaving an empty list around — prevents memory leaks in
            # long-running workers with many short-lived sessions.
            del self._subscribers[session_id]

    async def publish(
        self,
        session_id: str,
        event: dict[str, Any],
        topic: str = "session",
    ) -> None:
        """Publish an event to all matching subscribers of a session.

        Subscribers whose topic filter excludes `topic` are skipped without
        affecting the queue. Subscribers whose queue is full are removed
        (drop-event semantics, same as v2.1).
        """
        dead: list[_Subscriber] = []
        for sub in self._subscribers.get(session_id, []):
            if not sub.matches(topic):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(sub)

        for sub in dead:
            self.unsubscribe(session_id, sub.queue)

    # Test-only helper: lets unit tests inspect the subscriber count for a
    # session without poking the private attribute directly. Used by
    # `test_event_bus_topic_filter.py` to assert no-leak after unsubscribe.
    def _subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, []))


event_bus = EventBus()
