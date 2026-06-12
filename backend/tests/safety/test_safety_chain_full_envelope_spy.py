"""Ordered RUNTIME safety-envelope spy on the CURRENT ``PlanExecutor.execute`` path.

This pins, as an executable ordered assertion, the live runtime brake envelope
that today lives inside ``PlanExecutor.execute`` (``executor.py``):

  1. ``get_adapter(slug).execute(...)``            — the container run (``:61, :66``)
  2. ``EgressMonitor.monitor_log_line`` per log    — egress brake (``:77-81``)
  3. container-ID kill-switch registration         — ``execution.container_id`` set (``:68-74``)
  4. rescope harvest → ``RescopeService.pause_for_rescope`` on a new-host finding (``:167-206``)
  5. ``persist_kali_shim_block`` on ``SafetyViolation`` for a ``kali_*`` slug (``:103-133``)

It records the ACTUAL call order via monkeypatch spies and asserts the spec
order. When PR2 extracts ``execute_tool_through_safety_chain``, this same envelope
must still fire in this order (the brake bodies move verbatim into the helper; the
caller still drives them per step) — so this test guards the refactor too.

The FUTURE autonomous-path per-dispatch filter trio + tier gate
(``filter_plan_steps → filter_by_tier_flags → RiskFilter`` inside
``Performer._dispatch_tool``) lands in PR4a; an ``xfail`` placeholder at the bottom
captures that intent now so the chain decomposition is documented and tracked.

NOTE (C7 decomposition, surfaced for safety-reviewer sign-off): NO single function
runs the full spec-ordered chain end-to-end. The plan-time filter trio runs once
per plan in ``OrchestratorService.run`` / per-dispatch in ``_dispatch_tool``; the
runtime brakes run per-step in ``PlanExecutor.execute`` / the PR2 helper. The
immutable-chain invariant is therefore a DISTRIBUTED, test-enforced property — this
spy asserts the runtime half; ``test_autonomous_dispatch_runs_filter_trio_per_dispatch.py``
(PR4a) asserts the plan-time half.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentEvent
from app.safety.kali_allowlist import SafetyViolation
from app.orchestrator.executor import PlanExecutor


# ── deterministic fake adapters ──────────────────────────────────────────────

def _make_adapter(agent_type: str, *, findings: list[dict], raise_shim: bool = False):
    """Fake adapter yielding status→log→status(findings). If ``raise_shim`` the
    adapter raises ``SafetyViolation`` on iteration (mirrors a WhitelistShim
    rejection at build_command time for a kali_* slug)."""

    class _FakeAdapter:
        async def execute(
            self,
            target: dict,
            config: dict,
            execution_id_out: list[str] | None = None,
        ) -> AsyncGenerator[AgentEvent, None]:
            exec_id = f"container-{agent_type}"
            if execution_id_out is not None:
                execution_id_out.append(exec_id)
            if raise_shim:
                raise SafetyViolation(f"{agent_type}: denied flag")
            yield AgentEvent("status", agent_type, exec_id, {"status": "running"})
            yield AgentEvent("log", agent_type, exec_id, {"line": f"{agent_type}: Connecting to host"})
            yield AgentEvent(
                "status", agent_type, exec_id,
                {"status": "completed", "result": {"findings": findings}},
            )

    return _FakeAdapter()


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush():
        pass

    db.flush = _flush
    db.execute = AsyncMock()
    return db


# ── the ordered-envelope spy ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runtime_envelope_fires_in_spec_order_on_current_executor_path():
    """One step with a new-host finding exercises adapter.execute → egress →
    kill-registration → rescope, in order, on the current PlanExecutor path."""
    session_id = uuid.uuid4()
    # A new-host finding so the rescope harvest fires.
    findings = [{"new_hosts": [{"host": "new.example.com", "tier": "passive_recon"}]}]
    steps = [{"agent": "nmap", "order": 1, "config": {"tool_slug": "nmap"}}]

    calls: list[str] = []

    adapter = _make_adapter("nmap", findings=findings)
    real_execute = adapter.execute

    def _spy_execute(target, config, execution_id_out=None):
        calls.append("adapter.execute")
        return real_execute(target, config, execution_id_out)

    async def _spy_monitor_log_line(self, line, actor_id):  # noqa: ANN001
        calls.append("egress.monitor_log_line")
        return True  # safe → execution continues

    db = _make_db()
    executor = PlanExecutor(db)

    # Observe container-ID kill registration: the executor sets
    # ``execution.container_id`` from container_id_holder[0] (executor.py:68-74).
    # We spy on the AgentExecution attribute write via the patched event_bus path
    # indirectly — instead, record it by wrapping db.execute, which is where the
    # UPDATE ... container_id is issued.
    real_db_execute = db.execute

    async def _spy_db_execute(stmt, *a, **k):
        text = str(stmt).lower()
        if "container_id" in text:
            calls.append("kill_registration")
        return await real_db_execute(stmt, *a, **k)

    db.execute = _spy_db_execute

    with patch("app.orchestrator.safety_exec.get_adapter", return_value=adapter), \
         patch.object(adapter, "execute", side_effect=_spy_execute), \
         patch("app.orchestrator.executor.EgressMonitor.monitor_log_line", _spy_monitor_log_line), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()

        async def _pause(*a, **k):
            calls.append("rescope.pause_for_rescope")
            approval = MagicMock()
            approval.id = uuid.uuid4()
            return approval

        instance.pause_for_rescope = _pause
        MockRescope.return_value = instance

        await executor.execute(
            session_id=session_id,
            steps=steps,
            target={"ip_ranges": [], "domains": []},
            whitelist_rules={"ip_ranges": [], "domains": []},
            actor_id="actor-1",
        )

    # All four runtime stages fired.
    for stage in ("adapter.execute", "egress.monitor_log_line", "kill_registration",
                  "rescope.pause_for_rescope"):
        assert stage in calls, f"runtime stage {stage!r} never fired; order was {calls}"

    # Spec order: adapter.execute first; egress + kill-registration happen during
    # log iteration (before the terminal status); rescope harvest happens AFTER
    # the step's findings are collected (last).
    assert calls.index("adapter.execute") < calls.index("egress.monitor_log_line"), calls
    assert calls.index("adapter.execute") < calls.index("kill_registration"), calls
    assert calls.index("egress.monitor_log_line") < calls.index("rescope.pause_for_rescope"), calls
    assert calls.index("kill_registration") < calls.index("rescope.pause_for_rescope"), calls


@pytest.mark.asyncio
async def test_shim_block_audit_fires_on_kali_safety_violation():
    """A ``SafetyViolation`` raised for a ``kali_*`` slug persists a shim-block
    audit row via ``persist_kali_shim_block`` (executor.py:103-133)."""
    session_id = uuid.uuid4()
    steps = [{"agent": "kali_sqlmap", "order": 1, "config": {"tool_slug": "sqlmap"}}]

    adapter = _make_adapter("kali_sqlmap", findings=[], raise_shim=True)

    db = _make_db()
    executor = PlanExecutor(db)

    shim_calls: list[dict] = []

    async def _spy_persist(audit, **kwargs):  # noqa: ANN001
        shim_calls.append(kwargs)

    with patch("app.orchestrator.safety_exec.get_adapter", return_value=adapter), \
         patch("app.orchestrator.safety_exec.persist_kali_shim_block", _spy_persist), \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        await executor.execute(
            session_id=session_id,
            steps=steps,
            target={"ip_ranges": [], "domains": []},
            whitelist_rules={},
            actor_id="actor-1",
        )

    assert len(shim_calls) == 1, f"expected one shim-block audit, got {shim_calls}"
    assert shim_calls[0]["agent"] == "kali_sqlmap"
    assert shim_calls[0]["session_id"] == session_id
    assert "denied flag" in shim_calls[0]["reason"]


@pytest.mark.asyncio
async def test_non_kali_safety_violation_does_not_persist_shim_block():
    """A ``SafetyViolation`` for a NON-kali slug does NOT call
    ``persist_kali_shim_block`` (the shim-audit brake is kali-scoped at
    executor.py:108)."""
    session_id = uuid.uuid4()
    steps = [{"agent": "nmap", "order": 1, "config": {}}]

    adapter = _make_adapter("nmap", findings=[], raise_shim=True)

    db = _make_db()
    executor = PlanExecutor(db)

    shim_calls: list[dict] = []

    async def _spy_persist(audit, **kwargs):  # noqa: ANN001
        shim_calls.append(kwargs)

    with patch("app.orchestrator.safety_exec.get_adapter", return_value=adapter), \
         patch("app.orchestrator.safety_exec.persist_kali_shim_block", _spy_persist), \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        await executor.execute(
            session_id=session_id,
            steps=steps,
            target={"ip_ranges": [], "domains": []},
            whitelist_rules={},
            actor_id="actor-1",
        )

    assert shim_calls == [], f"non-kali slug must not persist shim block; got {shim_calls}"


# ── autonomous-path tier gate + runtime helper (PR4a — now live) ──────────────

@pytest.mark.asyncio
async def test_autonomous_dispatch_runs_filter_trio_with_tier_gate_then_runtime_helper():
    """PR4a: the autonomous lane runs the per-dispatch filter trio INCLUDING
    ``filter_by_tier_flags`` inside ``Performer._dispatch_tool``, THEN the shared
    runtime helper. The tier gate blocks an unapproved active-tier dispatch; with
    the flag the dispatch reaches the helper (adapter.execute) and executes.

    Companion to the runtime-envelope spy above (C7 distributed-invariant): this
    asserts the plan-time half on the autonomous path; that asserts the runtime half.
    """
    from app.orchestrator.performer import Performer

    # Unapproved active_recon dispatch is blocked by the per-dispatch tier gate.
    p = Performer(_make_db(), uuid.uuid4())
    p.bind_live_execution(
        target={"ip_ranges": [], "domains": []},
        approval_flags={}, whitelist_rules={}, actor_id="a",
    )
    blocked = await p._dispatch_tool("nmap", {"intent": "port_scan", "config": {}})
    assert blocked["approved"] is False
    assert blocked["blocked_reason"] == "tier_gate"

    # WITH the flag, the dispatch passes the trio and reaches the runtime helper.
    p2 = Performer(_make_db(), uuid.uuid4())
    p2.bind_live_execution(
        target={"ip_ranges": [], "domains": []},
        approval_flags={"approved_active_recon": True}, whitelist_rules={}, actor_id="a",
    )
    adapter = _make_adapter("nmap", findings=[{"type": "port"}])
    with patch("app.orchestrator.safety_exec.get_adapter", return_value=adapter):
        ok = await p2._dispatch_tool("nmap", {"intent": "port_scan", "config": {}})
    assert ok["approved"] is True
    assert ok.get("executed") is True
