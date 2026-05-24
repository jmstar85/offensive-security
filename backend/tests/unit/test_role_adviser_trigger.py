"""Adviser role + `should_trigger` predicate tests (v4.0 P2a)."""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.orchestrator.roles.adviser import Adviser, should_trigger


def test_should_trigger_returns_false_below_thresholds():
    """No fire when same-tool count and total count are below thresholds."""
    fires, reason = should_trigger(same_tool_max=4, total_tool_calls=9)
    assert fires is False
    assert reason is None


def test_should_trigger_fires_on_same_tool_threshold():
    fires, reason = should_trigger(
        same_tool_max=settings.adviser_trigger_same_tool,
        total_tool_calls=2,
    )
    assert fires is True
    assert "same_tool_called" in reason


def test_should_trigger_fires_on_total_threshold():
    fires, reason = should_trigger(
        same_tool_max=1,
        total_tool_calls=settings.adviser_trigger_total_tool,
    )
    assert fires is True
    assert "total_tool_calls" in reason


def test_adviser_palette_is_empty():
    """Adviser does not invoke tools — its only output is a guidance message."""
    role = Adviser()
    assert role.tools_allowed == []
    assert role.max_tool_calls == 0


@pytest.mark.asyncio
async def test_adviser_smoke_run_produces_guidance_message():
    role = Adviser()
    result = await role.run(performer=None, context={"trigger_reason": "loop_detected"})
    assert result.role_name == "adviser"
    assert result.finished is True
    assert "Adviser intervention" in result.messages[0]["content"]
    assert "loop_detected" in result.messages[0]["content"]
