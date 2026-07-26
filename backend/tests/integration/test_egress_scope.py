"""Per-step egress-violation blast radius (safety-reviewed).

Default is 'session' (fail-safe: any out-of-scope connection kills everything).
Opt-in 'step' contains the blast to the offending tool's container + fails that
step, continuing the remaining in-scope steps — EXCEPT an active_exploit-tier
egress or reaching the violation cap always escalates to a full session kill.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents.base import AgentEvent
from app.core.config import settings
from app.models.session import AgentExecution
from app.orchestrator import executor as ex_mod
from app.orchestrator import safety_exec as se
from app.orchestrator.executor import PlanExecutor, _summarize_findings
from app.orchestrator.safety_exec import SafetyExecResult, execute_tool_through_safety_chain
from app.safety.audit import AuditLogger
from app.safety.egress_monitor import EgressMonitor, EgressVerdict

OFFSCOPE = "connect() to 8.8.8.8:443"
WL = {"ip_ranges": ["45.33.32.0/24"]}


# ── monitor verdict / escalation logic (unit) ────────────────────────────────


@pytest.mark.asyncio
async def test_verdict_escalation_matrix(monkeypatch):
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 3)
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock):
        monkeypatch.setattr(settings, "osa_egress_violation_scope", "session")
        v = await EgressMonitor(uuid.uuid4(), WL).monitor_log_line(OFFSCOPE, "a")
        assert (v.safe, v.action) == (False, "kill_session")

        monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
        v = await EgressMonitor(uuid.uuid4(), WL).monitor_log_line(OFFSCOPE, "a")
        assert v.action == "stop_step"

        # active_exploit tier always escalates, even in step scope
        v = await EgressMonitor(uuid.uuid4(), WL).monitor_log_line(
            OFFSCOPE, "a", tier="active_exploit")
        assert v.action == "kill_session"


@pytest.mark.asyncio
async def test_circuit_breaker_escalates_after_cap(monkeypatch):
    monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 3)
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock):
        mon = EgressMonitor(uuid.uuid4(), WL)
        a1 = await mon.monitor_log_line(OFFSCOPE, "a")
        a2 = await mon.monitor_log_line(OFFSCOPE, "a")
        a3 = await mon.monitor_log_line(OFFSCOPE, "a")  # hits cap
    assert [a1.action, a2.action, a3.action] == ["stop_step", "stop_step", "kill_session"]


@pytest.mark.asyncio
async def test_consecutive_violations_report_distinct_dests(monkeypatch):
    """No stale dest across steps (per-call verdict, not a shared field)."""
    monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 99)
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock):
        mon = EgressMonitor(uuid.uuid4(), WL)
        v1 = await mon.monitor_log_line("connect() to 8.8.8.8:443", "a")
        v2 = await mon.monitor_log_line("connect() to 1.1.1.1:443", "a")
    assert v1.dest == "8.8.8.8" and v2.dest == "1.1.1.1"


@pytest.mark.asyncio
async def test_step_scope_records_metric_and_alert_without_session_kill(monkeypatch):
    """Step scope: durable metric + safety_alert fire, but stop_session does NOT."""
    import app.core.database as dbmod
    import app.core.events as evmod
    from app.observability.metrics import metrics

    monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 99)

    class _FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, *a):
            pass

        async def flush(self):
            pass

        async def commit(self):
            pass

    monkeypatch.setattr(dbmod, "async_session", lambda: _FakeDB())
    published: list = []

    async def _pub(sid, ev, topic="session"):
        published.append(ev)

    monkeypatch.setattr(evmod.event_bus, "publish", _pub)
    # stop_session must NOT be called in step scope; blow up if it is
    with patch("app.safety.kill_switch.KillSwitch.stop_session",
               new_callable=AsyncMock) as ks:
        before = metrics.egress_violation_total.value(scope="step", escalated="false")
        v = await EgressMonitor(uuid.uuid4(), WL).monitor_log_line(OFFSCOPE, "a")
    assert v.action == "stop_step"
    assert metrics.egress_violation_total.value(scope="step", escalated="false") == before + 1
    assert any(e.get("type") == "safety_alert" for e in published)
    ks.assert_not_awaited()


# ── safety_exec fail-closed (step scope) ─────────────────────────────────────


def _adapter(*, register: bool, stop_raises: bool):
    class _A:
        agent_type = "nmap"

        async def execute(self, target, config, holder=None):
            if register and holder is not None:
                holder.append("cid-1")
            yield AgentEvent("status", "nmap", "cid-1", {"status": "running"})
            yield AgentEvent("log", "nmap", "cid-1", {"line": OFFSCOPE})
            yield AgentEvent("status", "nmap", "cid-1",
                             {"status": "completed", "result": {"findings": []}})

        async def stop(self, cid):
            if stop_raises:
                raise RuntimeError("stop boom")

    return _A()


@pytest.mark.asyncio
async def test_safety_exec_step_egress_fail_closed_when_stop_raises(db, monkeypatch):
    monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 99)
    monkeypatch.setattr(se, "get_adapter", lambda slug: _adapter(register=True, stop_raises=True))
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock):
        mon = EgressMonitor(uuid.uuid4(), WL)
        result = await execute_tool_through_safety_chain(
            {"agent": "nmap", "config": {}, "tier": "active_recon"}, WL,
            egress_monitor=mon, audit=AuditLogger(db),
            session_id=uuid.uuid4(), actor_id="a")
    # egress signal set despite adapter.stop raising (never falls to generic error)
    assert result.egress_violation == "8.8.8.8"
    assert result.killed is False
    assert result.error is None


@pytest.mark.asyncio
async def test_safety_exec_step_egress_fail_closed_when_holder_empty(db, monkeypatch):
    monkeypatch.setattr(settings, "osa_egress_violation_scope", "step")
    monkeypatch.setattr(settings, "osa_egress_violation_cap", 99)
    monkeypatch.setattr(se, "get_adapter", lambda slug: _adapter(register=False, stop_raises=False))
    with patch.object(EgressMonitor, "_trigger_kill", new_callable=AsyncMock):
        mon = EgressMonitor(uuid.uuid4(), WL)
        result = await execute_tool_through_safety_chain(
            {"agent": "nmap", "config": {}, "tier": "active_recon"}, WL,
            egress_monitor=mon, audit=AuditLogger(db),
            session_id=uuid.uuid4(), actor_id="a")
    assert result.egress_violation == "8.8.8.8"  # fails closed even with no container id
    assert result.killed is False


# ── executor: step fails, run CONTINUES ──────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_step_egress_fails_step_and_continues(db, monkeypatch):
    sid = uuid.uuid4()
    calls: list[str] = []

    async def _fake_chain(step, target, **kw):
        calls.append(step["agent"])
        if step["agent"] == "nmap":
            return SafetyExecResult(egress_violation="8.8.8.8")
        return SafetyExecResult(findings=[{"port": 80}])

    monkeypatch.setattr(ex_mod, "execute_tool_through_safety_chain", _fake_chain)
    steps = [
        {"id": "s1", "order": 1, "agent": "nmap", "action": "port_scan",
         "config": {}, "tier": "active_recon"},
        {"id": "s2", "order": 2, "agent": "httpx", "action": "http",
         "config": {}, "tier": "passive_low_touch"},
    ]
    findings = await PlanExecutor(db).execute(sid, steps, WL, WL, "actor")

    assert calls == ["nmap", "httpx"]          # step 2 RAN — run not aborted
    assert findings == [{"port": 80}]
    rows = {r.agent_type: r for r in (await db.execute(
        select(AgentExecution).where(AgentExecution.session_id == sid))).scalars().all()}
    assert rows["nmap"].status == "failed"
    assert rows["nmap"].output_json["reason"] == "egress_violation"
    assert rows["httpx"].status == "completed"


@pytest.mark.asyncio
async def test_executor_session_kill_aborts_remaining_steps(db, monkeypatch):
    sid = uuid.uuid4()
    calls: list[str] = []

    async def _fake_chain(step, target, **kw):
        calls.append(step["agent"])
        if step["agent"] == "nmap":
            return SafetyExecResult(killed=True)
        return SafetyExecResult(findings=[{"port": 80}])

    monkeypatch.setattr(ex_mod, "execute_tool_through_safety_chain", _fake_chain)
    steps = [
        {"id": "s1", "order": 1, "agent": "nmap", "action": "port_scan", "config": {}, "tier": "active_recon"},
        {"id": "s2", "order": 2, "agent": "httpx", "action": "http", "config": {}, "tier": "passive_low_touch"},
    ]
    await PlanExecutor(db).execute(sid, steps, WL, WL, "actor")
    assert calls == ["nmap"]  # session kill aborted before step 2


# ── narration arm ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_narrate_step_egress_arm(db):
    ex = PlanExecutor(db)
    sid = uuid.uuid4()
    from datetime import datetime, timezone

    from app.models.msgchain import MsgChain

    await ex._narrate_step(
        sid, {"agent": "katana", "action": "crawl"}, {"target": "x"},
        datetime.now(timezone.utc),
        SimpleNamespace(killed=False, egress_violation="8.8.8.8",
                        safety_violation=None, error=None, findings=[]))
    row = (await db.execute(select(MsgChain).where(MsgChain.pentest_session_id == sid))).scalars().one()
    assert row.status == "failed"
    assert "out-of-scope egress" in row.messages_json[-1]["content"]
