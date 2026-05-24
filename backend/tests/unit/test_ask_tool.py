"""ask_tool unit tests (v4.0 P4)."""
from __future__ import annotations

import uuid

import pytest

from app.core.events import EventBus
from app.orchestrator import ask_tool


@pytest.mark.asyncio
async def test_ask_publishes_on_tasks_topic(monkeypatch):
    """`ask` publishes an `ask_pending` event on the `tasks` topic so the
    Tasks panel can surface it inline next to the SubTask list."""
    fake_bus = EventBus()
    monkeypatch.setattr(ask_tool, "event_bus", fake_bus)

    sid = uuid.uuid4()
    q = fake_bus.subscribe(str(sid), topics={"tasks"})

    response = await ask_tool.ask(
        session_id=sid,
        role_name="pentester",
        question="Authorized to scan 10.10.10.0/24?",
        options=["yes", "no", "ask again later"],
    )

    received = await q.get()
    assert received["type"] == "ask_pending"
    assert received["role"] == "pentester"
    assert received["question"].startswith("Authorized to scan")
    assert received["options"] == ["yes", "no", "ask again later"]
    assert response.sentinel == "ask_pending"


@pytest.mark.asyncio
async def test_ask_default_options_emits_empty_list(monkeypatch):
    """No options provided → publishes an empty list (not None)."""
    fake_bus = EventBus()
    monkeypatch.setattr(ask_tool, "event_bus", fake_bus)

    sid = uuid.uuid4()
    q = fake_bus.subscribe(str(sid), topics={"tasks"})

    await ask_tool.ask(session_id=sid, role_name="generator", question="Confirm target?")
    received = await q.get()
    assert received["options"] == []
