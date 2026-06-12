"""ask_tool — escalation primitive (v4.0 P4).

A role calls `ask(performer, question, options)` to surface a clarifying
question to the operator. The function publishes an `ask_event` on the
`event_bus` `tasks` topic (the Tasks panel renders it inline alongside the
Automation chat) and returns a sentinel that the calling role's chain
should treat as "block on user reply".

The actual user reply comes back through the existing
`/pentest-sessions/{id}/messages` endpoint and the turn-based interview
(`CoordinatorService.run_interview_turn` → `AmbiguityLoop`). `ask` does NOT
hold a coroutine open waiting for the reply, and the interview runs OUTSIDE the
`_PerformerLease` (PR5): each turn is a discrete request that returns, so a
session mid-interview cannot starve the per-session Performer concurrency cap.
The lease is acquired only once the interview terminates and dispatch begins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.events import event_bus


@dataclass
class AskResponse:
    """Sentinel returned by `ask` so the caller can persist it as an event."""

    question: str
    options: list[str] | None
    sentinel: str = "ask_pending"


async def ask(
    session_id: UUID,
    role_name: str,
    question: str,
    options: list[str] | None = None,
) -> AskResponse:
    """Publish an ask event to the Tasks panel and return the pending sentinel."""
    event: dict[str, Any] = {
        "type": "ask_pending",
        "role": role_name,
        "question": question,
        "options": options or [],
    }
    await event_bus.publish(str(session_id), event, topic="tasks")
    return AskResponse(question=question, options=options)
