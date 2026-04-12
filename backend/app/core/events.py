"""Async event bus for orchestrator → WebSocket broadcasting."""
import asyncio
import uuid
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers[session_id].append(q)
        return q

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        try:
            self._subscribers[session_id].remove(queue)
        except ValueError:
            pass

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        dead = []
        for q in self._subscribers[session_id]:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(session_id, q)


event_bus = EventBus()
