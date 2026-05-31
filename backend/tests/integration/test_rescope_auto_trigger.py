"""PR2b.3 — PlanExecutor auto-triggers RescopeService when step findings contain
new hosts. Uses AsyncMock/MagicMock only — no real DB or registry required."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.executor import PlanExecutor
from app.orchestrator.rescope_service import DiscoveredTarget


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    # flush() must be awaitable and populate execution.id
    async def _flush():
        pass
    db.flush = _flush
    db.execute = AsyncMock()
    return db


def _make_adapter_event(findings: list[dict]):
    """Return a mock async-generator adapter whose single event carries findings."""
    event = MagicMock()
    event.event_type = "status"
    event.agent_type = "test_agent"
    event.data = {"result": {"findings": findings}}

    async def _gen(*args, **kwargs):
        yield event

    adapter = MagicMock()
    adapter.execute = _gen
    return adapter


def _make_steps(agent: str = "test_agent") -> list[dict]:
    return [{"agent": agent, "config": {}, "order": 1}]


def _make_approval(rescope_id: uuid.UUID | None = None) -> MagicMock:
    approval = MagicMock()
    approval.id = rescope_id or uuid.uuid4()
    return approval


# ---------------------------------------------------------------------------
# test_step_with_new_hosts_triggers_rescope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_with_new_hosts_triggers_rescope():
    session_id = uuid.uuid4()
    findings = [{"new_hosts": [{"host": "foo.example.com", "tier": "passive_recon"}]}]
    approval = _make_approval()

    db = _make_db()
    executor = PlanExecutor(db)

    with patch("app.orchestrator.executor.get_adapter", return_value=_make_adapter_event(findings)), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        instance.pause_for_rescope = AsyncMock(return_value=approval)
        MockRescope.return_value = instance

        result = await executor.execute(
            session_id=session_id,
            steps=_make_steps(),
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    # pause_for_rescope called with exactly one DiscoveredTarget
    instance.pause_for_rescope.assert_awaited_once()
    call_kwargs = instance.pause_for_rescope.call_args.kwargs
    assert len(call_kwargs["discovered"]) == 1
    dt: DiscoveredTarget = call_kwargs["discovered"][0]
    assert dt.host == "foo.example.com"
    assert dt.tier == "passive_recon"

    # session_update event with paused_for_rescope fired
    session_update_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "session_update"
    ]
    assert len(session_update_calls) == 1
    assert session_update_calls[0].args[1]["status"] == "paused_for_rescope"
    assert session_update_calls[0].args[1]["rescope_id"] == str(approval.id)

    # executor returned early (agent_completed NOT published after rescope pause)
    completed_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "agent_completed"
    ]
    assert len(completed_calls) == 0

    # findings still returned
    assert result == [{"new_hosts": [{"host": "foo.example.com", "tier": "passive_recon"}]}]


# ---------------------------------------------------------------------------
# test_step_with_finding_marked_is_new_triggers_rescope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_with_finding_marked_is_new_triggers_rescope():
    session_id = uuid.uuid4()
    findings = [{"host": "bar.com", "tier": "active_recon", "is_new": True}]
    approval = _make_approval()

    db = _make_db()
    executor = PlanExecutor(db)

    with patch("app.orchestrator.executor.get_adapter", return_value=_make_adapter_event(findings)), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        instance.pause_for_rescope = AsyncMock(return_value=approval)
        MockRescope.return_value = instance

        await executor.execute(
            session_id=session_id,
            steps=_make_steps(),
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    instance.pause_for_rescope.assert_awaited_once()
    call_kwargs = instance.pause_for_rescope.call_args.kwargs
    assert len(call_kwargs["discovered"]) == 1
    dt: DiscoveredTarget = call_kwargs["discovered"][0]
    assert dt.host == "bar.com"
    assert dt.tier == "active_recon"


# ---------------------------------------------------------------------------
# test_step_with_no_new_hosts_does_not_trigger_rescope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step_with_no_new_hosts_does_not_trigger_rescope():
    session_id = uuid.uuid4()
    findings = [{"type": "port", "port": 80, "service": "http"}]

    db = _make_db()
    executor = PlanExecutor(db)

    with patch("app.orchestrator.executor.get_adapter", return_value=_make_adapter_event(findings)), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        MockRescope.return_value = instance

        result = await executor.execute(
            session_id=session_id,
            steps=_make_steps(),
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    instance.pause_for_rescope.assert_not_awaited()

    # agent_completed WAS published (no early return)
    completed_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "agent_completed"
    ]
    assert len(completed_calls) == 1


# ---------------------------------------------------------------------------
# test_rescope_service_returning_none_does_not_pause
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rescope_service_returning_none_does_not_pause():
    """When all discovered hosts are wildcard-blocked, pause_for_rescope returns
    None and execution continues to the next step (agent_completed fires)."""
    session_id = uuid.uuid4()
    findings = [{"new_hosts": [{"host": "blocked.internal", "tier": "passive_recon"}]}]

    db = _make_db()
    executor = PlanExecutor(db)

    with patch("app.orchestrator.executor.get_adapter", return_value=_make_adapter_event(findings)), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        instance.pause_for_rescope = AsyncMock(return_value=None)
        MockRescope.return_value = instance

        result = await executor.execute(
            session_id=session_id,
            steps=_make_steps(),
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    # pause_for_rescope was called but returned None — no session_update
    instance.pause_for_rescope.assert_awaited_once()
    session_update_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "session_update"
    ]
    assert len(session_update_calls) == 0

    # agent_completed was still published
    completed_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "agent_completed"
    ]
    assert len(completed_calls) == 1


# ---------------------------------------------------------------------------
# test_rescope_exception_audited_but_does_not_kill_execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rescope_exception_audited_but_does_not_kill_execution():
    """When RescopeService.pause_for_rescope raises, an audit row is written
    with action='rescope_trigger_failed' and the next step still executes."""
    session_id = uuid.uuid4()
    findings = [{"new_hosts": [{"host": "err.example.com", "tier": "passive_recon"}]}]

    # Two steps so we can verify the second step runs after the first raises.
    steps = [
        {"agent": "agent_a", "config": {}, "order": 1},
        {"agent": "agent_b", "config": {}, "order": 2},
    ]

    # Both adapters yield the same findings so both trigger the rescope path.
    adapter_a = _make_adapter_event(findings)
    adapter_b = _make_adapter_event([])  # second step has no new hosts

    db = _make_db()
    executor = PlanExecutor(db)

    audit_calls: list[dict] = []

    async def _fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    with patch("app.orchestrator.executor.get_adapter", side_effect=[adapter_a, adapter_b]), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        instance.pause_for_rescope = AsyncMock(side_effect=RuntimeError("db down"))
        MockRescope.return_value = instance

        # Patch audit on the executor instance after construction
        executor._audit.log = _fake_audit_log

        result = await executor.execute(
            session_id=session_id,
            steps=steps,
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    # Audit log captured the failure
    assert any(c.get("action") == "rescope_trigger_failed" for c in audit_calls), (
        f"Expected rescope_trigger_failed in audit calls, got: {audit_calls}"
    )

    # Both steps completed (agent_completed fired twice)
    completed_calls = [
        c for c in mock_bus.publish.call_args_list
        if c.args[1].get("type") == "agent_completed"
    ]
    assert len(completed_calls) == 2


# ---------------------------------------------------------------------------
# test_discovered_target_tier_default_is_passive_recon
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discovered_target_tier_default_is_passive_recon():
    """When a finding's new_hosts entry lacks a 'tier' field, DiscoveredTarget
    is created with tier='passive_recon'."""
    session_id = uuid.uuid4()
    findings = [{"new_hosts": [{"host": "notier.example.com"}]}]  # no tier key
    approval = _make_approval()

    db = _make_db()
    executor = PlanExecutor(db)

    with patch("app.orchestrator.executor.get_adapter", return_value=_make_adapter_event(findings)), \
         patch("app.orchestrator.executor.RescopeService") as MockRescope, \
         patch("app.orchestrator.executor.event_bus") as mock_bus:

        mock_bus.publish = AsyncMock()
        instance = AsyncMock()
        instance.pause_for_rescope = AsyncMock(return_value=approval)
        MockRescope.return_value = instance

        await executor.execute(
            session_id=session_id,
            steps=_make_steps(),
            target={"host": "target.com"},
            whitelist_rules={},
            actor_id="actor-1",
        )

    call_kwargs = instance.pause_for_rescope.call_args.kwargs
    dt: DiscoveredTarget = call_kwargs["discovered"][0]
    assert dt.tier == "passive_recon"
