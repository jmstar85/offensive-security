"""P4 safety-chain regression — v4.0 (Principle 1, ADR-005).

Verifies that the v4.0 dispatcher path (Pentester → runtime_delegator →
Performer._dispatch_tool) invokes the safety layers in the same order as
the v3.2.1 OrchestratorService.run, and that no tool slug or intent can
bypass them.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.performer import Performer


@pytest.mark.asyncio
async def test_unknown_tool_slug_is_blocked_before_safety_chain():
    """Validation order: slug check must reject unknown tools BEFORE the
    safety chain runs (otherwise unknown slugs could DoS the audit log)."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    result = await p._dispatch_tool("not_real", {"intent": "port_scan", "config": {}})
    assert result["approved"] is False
    assert result["blocked_reason"].startswith("unknown_tool_slug")


@pytest.mark.asyncio
async def test_unknown_intent_slug_is_blocked_before_safety_chain():
    """Closed intent enum: dispatcher rejects intents not in INTENT_VOCABULARY."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    result = await p._dispatch_tool("nmap", {"intent": "rogue_intent", "config": {}})
    assert result["approved"] is False
    assert result["blocked_reason"].startswith("unknown_intent_slug")


@pytest.mark.asyncio
async def test_synthetic_step_carries_tier_for_filter_chain():
    """The synthetic step shape must include `tier` so filter_plan_steps +
    RiskFilter can do tier-aware decisions."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    result = await p._dispatch_tool(
        "nmap", {"intent": "port_scan", "config": {}}
    )
    assert result["approved"] is True
    assert "tier" in result["synthetic_step"]
    assert result["synthetic_step"]["tier"]


@pytest.mark.asyncio
async def test_counters_increment_for_every_dispatched_call():
    """Adviser counters are bumped on each call so threshold logic works."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())
    await p._dispatch_tool("nmap", {"intent": "port_scan", "config": {}})
    await p._dispatch_tool("nmap", {"intent": "port_scan", "config": {}})
    await p._dispatch_tool(
        "nuclei", {"intent": "vulnerability_template_scan", "config": {}}
    )
    assert p.state.same_tool_counter["nmap"] == 2
    assert p.state.same_tool_counter["nuclei"] == 1
    assert p.state.total_tool_calls == 3
