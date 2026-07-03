"""Runtime delegator tests (v4.0 P4)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

# Import seed module so ROLE_REGISTRY is populated.
from app.orchestrator.roles import seed as _seed  # noqa: F401
from app.orchestrator.performer import Performer
from app.orchestrator.runtime_delegator import delegate_tool_call


@pytest.mark.asyncio
async def test_delegate_routes_adapter_tool_call_through_dispatcher():
    """A tool slug in `list_agent_types()` routes through `_dispatch_tool`."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())

    out = await delegate_tool_call(
        p,
        "nmap",
        {"intent": "port_scan", "config": {"targets": ["127.0.0.1"]}},
    )
    assert out["kind"] == "adapter"
    assert out["result"]["approved"] is True
    assert out["result"]["tool"] == "nmap"


@pytest.mark.asyncio
async def test_delegate_routes_role_slug_through_role_registry():
    """A slug that matches a role name runs the role's `run()` — but ONLY when the
    trusted automation caller opts in via ``allow_role_invocation=True`` (PR7
    default-deny). ``memorist`` is non-consuming so it needs no client_factory."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())

    out = await delegate_tool_call(
        p, "memorist", {"query": "x"}, allow_role_invocation=True
    )
    assert out["kind"] == "role"
    assert out["result"]["role_name"] == "memorist"


@pytest.mark.asyncio
async def test_delegate_default_deny_refuses_role_slug():
    """PR7 (Improvement 2 / Finding 3): the ROLE_REGISTRY role-invocation branch is
    DEFAULT-DENY — an untrusted caller (default ``allow_role_invocation=False``)
    gets a refusal, NOT a sub-role launch."""
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())

    out = await delegate_tool_call(p, "memorist", {"query": "x"})
    assert out["kind"] == "refused"
    assert out["result"]["approved"] is False
    assert "role_invocation_denied" in out["result"]["blocked_reason"]


@pytest.mark.asyncio
async def test_delegate_rejects_unknown_slug():
    db = AsyncMock()
    p = Performer(db=db, session_id=uuid.uuid4())

    out = await delegate_tool_call(p, "definitely_not_a_thing", {})
    assert out["kind"] == "unknown"
    assert "unknown_tool_or_role" in out["result"]["blocked_reason"]
