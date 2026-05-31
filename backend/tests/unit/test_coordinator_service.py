"""Unit tests for CoordinatorService, UnderstandingBuilder, and PlanOfWorkBuilder."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import (
    CoordinatorService,
    PlanOfWorkBuilder,
    ReplayLaneViolation,
    UnderstandingBuilder,
    UnderstandingOfTarget,
    PlanOfWork,
)


SESSION_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ACTOR_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# _FakeDB — minimal AsyncSession stand-in
# ---------------------------------------------------------------------------

class _FakeRow:
    def __init__(self, session_obj):
        self._obj = session_obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    def __init__(self, session_obj=None):
        self._session_obj = session_obj
        self._added: list = []
        self._flushed = False
        self._executed: list = []

    def add(self, obj):
        self._added.append(obj)
        if not hasattr(obj, "id") or obj.id is None:
            import uuid as _uuid
            object.__setattr__(obj, "id", _uuid.uuid4()) if hasattr(obj, "__dict__") else None
            try:
                obj.id = _uuid.uuid4()
            except Exception:
                pass

    async def flush(self):
        self._flushed = True
        for obj in self._added:
            if getattr(obj, "id", None) is None:
                try:
                    obj.id = uuid.uuid4()
                except Exception:
                    pass

    async def execute(self, stmt):
        self._executed.append(stmt)
        return _FakeRow(self._session_obj)

    async def commit(self):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coordinator_run_fresh_plan_emits_two_events():
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    published = []

    async def _fake_publish(session_id, event, topic="session"):
        published.append((session_id, event, topic))

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit, \
         patch("app.core.events.event_bus.publish", side_effect=_fake_publish):
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)
        understanding, plan_of_work = await svc.run(
            session_id=SESSION_ID,
            prompt="scan example.com for vulnerabilities",
            target={"domains": ["example.com"], "ip_ranges": []},
            actor_id=ACTOR_ID,
            lane="fresh_plan",
        )

    coordinator_publishes = [p for p in published if p[2] == "coordinator"]
    assert len(coordinator_publishes) == 2
    event_types = {p[1]["type"] for p in coordinator_publishes}
    assert event_types == {"understanding_built", "plan_of_work_built"}


@pytest.mark.asyncio
async def test_coordinator_run_saved_workflow_without_opt_in_raises():
    fake_db = _FakeDB()
    svc = CoordinatorService(fake_db)

    with pytest.raises(ReplayLaneViolation):
        await svc.run(
            session_id=SESSION_ID,
            prompt="scan",
            target={"domains": [], "ip_ranges": []},
            actor_id=ACTOR_ID,
            lane="saved_workflow",
            replay_opt_in=False,
        )


@pytest.mark.asyncio
async def test_coordinator_run_saved_workflow_with_opt_in_succeeds():
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit, \
         patch("app.core.events.event_bus.publish", new_callable=AsyncMock):
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)
        understanding, plan_of_work = await svc.run(
            session_id=SESSION_ID,
            prompt="scan example.com",
            target={"domains": ["example.com"], "ip_ranges": []},
            actor_id=ACTOR_ID,
            lane="saved_workflow",
            replay_opt_in=True,
        )

    assert isinstance(understanding, UnderstandingOfTarget)
    assert isinstance(plan_of_work, PlanOfWork)


@pytest.mark.asyncio
async def test_understanding_builder_detects_web_app_target_kind():
    builder = UnderstandingBuilder()
    result = await builder.build(
        prompt="test",
        target={"domains": ["ex.com"], "ip_ranges": []},
    )
    assert result.target_kind == "web_app"


@pytest.mark.asyncio
async def test_plan_of_work_builder_emits_three_phases():
    u = UnderstandingOfTarget(target_kind="web_app", objectives=[])
    builder = PlanOfWorkBuilder()
    plan = await builder.build(u, "scan the host")
    assert plan.ordered_phases == ["recon", "exploit", "extraction"]


@pytest.mark.asyncio
async def test_coordinator_persists_understanding_and_plan_to_session():
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    captured_updates = {}

    original_execute = fake_db.execute

    async def _tracking_execute(stmt):
        # Track the update statement values
        try:
            if hasattr(stmt, "_values"):
                captured_updates.update(stmt._values)
        except Exception:
            pass
        return _FakeRow(fake_session)

    fake_db.execute = _tracking_execute

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit, \
         patch("app.core.events.event_bus.publish", new_callable=AsyncMock):
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)
        understanding, plan_of_work = await svc.run(
            session_id=SESSION_ID,
            prompt="recon, exploit target.com",
            target={"domains": ["target.com"], "ip_ranges": []},
            actor_id=ACTOR_ID,
            lane="fresh_plan",
        )

    # Verify the returned objects have the right shape
    assert understanding.target_kind == "web_app"
    assert "recon" in plan_of_work.ordered_phases
    assert plan_of_work.objectives  # at least one objective parsed from prompt


@pytest.mark.asyncio
async def test_jaccard_drift_below_threshold_fires_audit():
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit:
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)

        # saved plan has steps with agents named very differently from fresh objectives
        saved_plan_json = {
            "steps": [
                {"agent": "xyzzy_tool_alpha"},
                {"agent": "xyzzy_tool_beta"},
                {"agent": "xyzzy_tool_gamma"},
            ]
        }
        fresh_understanding = UnderstandingOfTarget(target_kind="web_app")
        fresh_plan = PlanOfWork(
            objectives=["completely different objective here", "another unrelated goal"],
            ordered_phases=["recon", "exploit", "extraction"],
        )

        drifted = await svc.maybe_run_replay_drift_check(
            session_id=SESSION_ID,
            saved_plan_json=saved_plan_json,
            fresh_understanding=fresh_understanding,
            fresh_plan_of_work=fresh_plan,
            actor_id=ACTOR_ID,
        )

    assert drifted is True
    mock_audit_instance.log.assert_awaited_once()
    call_kwargs = mock_audit_instance.log.await_args.kwargs
    assert call_kwargs["action"] == "coordinator.replay_drift_detected"
    assert "jaccard" in call_kwargs["details"]
