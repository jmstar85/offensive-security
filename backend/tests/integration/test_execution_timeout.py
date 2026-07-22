"""FIX (session 9a7d4563): a tool container that never exits (e.g. a full-template
nuclei scan against a filtered host) must NOT hang the whole sequential run.
execute_tool_through_safety_chain now enforces a per-step wall-clock timeout: on
expiry it stops the container and returns an error so the run continues.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agents.base import AgentEvent
from app.orchestrator import safety_exec
from app.safety.audit import AuditLogger
from app.safety.egress_monitor import EgressMonitor


class _HungAdapter:
    agent_type = "nmap"

    def __init__(self) -> None:
        self.stopped: str | None = None

    async def execute(self, target, config, holder):  # noqa: ANN001
        holder.append("cid-hung")
        yield AgentEvent("status", "nmap", "cid-hung", {"status": "running"})
        await asyncio.sleep(30)  # never returns within the test timeout
        yield AgentEvent(
            "status", "nmap", "cid-hung", {"status": "completed", "result": {"findings": []}}
        )

    async def stop(self, cid):  # noqa: ANN001
        self.stopped = cid


@pytest.mark.asyncio
async def test_execution_timeout_stops_hung_tool_and_errors(db, monkeypatch):
    adapter = _HungAdapter()
    monkeypatch.setattr(safety_exec, "get_adapter", lambda _slug: adapter)

    result = await safety_exec.execute_tool_through_safety_chain(
        {"agent": "nmap", "config": {"timeout_secs": 1}},
        {"ip_ranges": ["10.0.0.1"], "domains": []},
        egress_monitor=EgressMonitor(uuid.uuid4(), {"ip_ranges": ["10.0.0.1"], "domains": []}),
        audit=AuditLogger(db),
        session_id=uuid.uuid4(),
        actor_id="tester",
    )

    assert result.error is not None
    assert "timed out" in result.error
    assert adapter.stopped == "cid-hung"  # the runaway container was stopped
    assert result.killed is False


class _FastAdapter:
    agent_type = "nmap"

    async def execute(self, target, config, holder):  # noqa: ANN001
        holder.append("cid-ok")
        yield AgentEvent("status", "nmap", "cid-ok", {"status": "running"})
        yield AgentEvent(
            "status", "nmap", "cid-ok",
            {"status": "completed", "result": {"findings": [{"port": 22}]}},
        )

    async def stop(self, cid):  # noqa: ANN001
        raise AssertionError("stop() must not be called on a tool that finishes in time")


@pytest.mark.asyncio
async def test_fast_tool_completes_within_timeout(db, monkeypatch):
    monkeypatch.setattr(safety_exec, "get_adapter", lambda _slug: _FastAdapter())
    result = await safety_exec.execute_tool_through_safety_chain(
        {"agent": "nmap", "config": {"timeout_secs": 10}},
        {"ip_ranges": ["10.0.0.1"], "domains": []},
        egress_monitor=EgressMonitor(uuid.uuid4(), {"ip_ranges": ["10.0.0.1"], "domains": []}),
        audit=AuditLogger(db),
        session_id=uuid.uuid4(),
        actor_id="tester",
    )
    assert result.error is None
    assert result.findings == [{"port": 22}]
