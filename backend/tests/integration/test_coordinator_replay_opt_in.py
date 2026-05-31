"""Integration: saved-workflow lane with osa_coordinator_replay_enabled=True
and no skip_coordinator_replay flag → CoordinatorService.run IS invoked,
drift check runs, and a divergent fresh plan fires the drift audit.
"""
from __future__ import annotations

import copy
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import (
    CoordinatorService,
    PlanOfWork,
    UnderstandingOfTarget,
)
from app.safety.audit import AuditLogger


SESSION_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
ACTOR_ID = "00000000-0000-0000-0000-000000000003"

SAVED_PLAN = {
    "steps": [
        {"agent": "xyzzy_tool_alpha"},
        {"agent": "xyzzy_tool_beta"},
    ]
}


class _FakeRow:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    def __init__(self, session_obj):
        self._session_obj = session_obj
        self.audit_rows: list[dict] = []

    async def execute(self, stmt):
        return _FakeRow(self._session_obj)

    async def commit(self):
        pass

    def add(self, obj):
        from app.models.audit import AuditLog
        if isinstance(obj, AuditLog):
            self.audit_rows.append({
                "action": obj.action,
                "details": obj.details_json,
            })

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_replay_opt_in_invokes_coordinator_and_drift_check():
    """When replay is enabled and plan_json present, CoordinatorService.run
    is called AND drift check is invoked."""
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    coordinator_run_called = []
    drift_check_called = []

    original_run = CoordinatorService.run
    original_drift = CoordinatorService.maybe_run_replay_drift_check

    async def _spy_run(self, *, session_id, prompt, target, actor_id, lane, replay_opt_in=False):
        coordinator_run_called.append({"lane": lane, "replay_opt_in": replay_opt_in})
        return (
            UnderstandingOfTarget(target_kind="web_app"),
            PlanOfWork(
                objectives=["completely different objective here", "another unrelated goal"],
                ordered_phases=["recon", "exploit", "extraction"],
            ),
        )

    async def _spy_drift(self, *, session_id, saved_plan_json, fresh_understanding,
                         fresh_plan_of_work, actor_id):
        drift_check_called.append(True)
        return await original_drift(
            self,
            session_id=session_id,
            saved_plan_json=saved_plan_json,
            fresh_understanding=fresh_understanding,
            fresh_plan_of_work=fresh_plan_of_work,
            actor_id=actor_id,
        )

    with patch.object(CoordinatorService, "run", _spy_run), \
         patch.object(CoordinatorService, "maybe_run_replay_drift_check", _spy_drift), \
         patch("app.orchestrator.coordinator.AuditLogger") as MockAudit:
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        saved_plan_copy = copy.deepcopy(SAVED_PLAN)

        session_id = SESSION_ID
        actor_id = ACTOR_ID
        prompt = "recon target"
        target = {"domains": [], "ip_ranges": []}
        lane = "saved_workflow"
        replay_opt_in = True

        coordinator = CoordinatorService(fake_db)
        understanding, plan_of_work = await coordinator.run(
            session_id=session_id, prompt=prompt, target=target,
            actor_id=actor_id, lane=lane, replay_opt_in=replay_opt_in,
        )

        await coordinator.maybe_run_replay_drift_check(
            session_id=session_id,
            saved_plan_json=saved_plan_copy,
            fresh_understanding=understanding,
            fresh_plan_of_work=plan_of_work,
            actor_id=actor_id,
        )

    assert len(coordinator_run_called) == 1
    assert coordinator_run_called[0]["lane"] == "saved_workflow"
    assert coordinator_run_called[0]["replay_opt_in"] is True
    assert len(drift_check_called) == 1


@pytest.mark.asyncio
async def test_saved_plan_json_unchanged_after_run():
    """The saved plan_json dict must not be mutated by coordinator logic."""
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    saved_plan_copy = copy.deepcopy(SAVED_PLAN)
    original_saved = copy.deepcopy(SAVED_PLAN)

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit, \
         patch("app.core.events.event_bus.publish", new_callable=AsyncMock):
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)
        understanding, plan_of_work = await svc.run(
            session_id=SESSION_ID,
            prompt="scan target.net",
            target={"domains": ["target.net"], "ip_ranges": []},
            actor_id=ACTOR_ID,
            lane="saved_workflow",
            replay_opt_in=True,
        )

        await svc.maybe_run_replay_drift_check(
            session_id=SESSION_ID,
            saved_plan_json=saved_plan_copy,
            fresh_understanding=understanding,
            fresh_plan_of_work=plan_of_work,
            actor_id=ACTOR_ID,
        )

    # saved_plan_copy must be byte-equal to original after the call
    assert saved_plan_copy == original_saved


@pytest.mark.asyncio
async def test_divergent_fresh_plan_fires_drift_audit():
    """A fresh plan with objectives very different from saved steps
    triggers jaccard < 0.6 and fires 'coordinator.replay_drift_detected'."""
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit:
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(fake_db)
        divergent_plan = PlanOfWork(
            objectives=["completely different objective here", "another unrelated goal"],
            ordered_phases=["recon", "exploit", "extraction"],
        )
        drifted = await svc.maybe_run_replay_drift_check(
            session_id=SESSION_ID,
            saved_plan_json=SAVED_PLAN,
            fresh_understanding=UnderstandingOfTarget(target_kind="web_app"),
            fresh_plan_of_work=divergent_plan,
            actor_id=ACTOR_ID,
        )

    assert drifted is True
    mock_audit_instance.log.assert_awaited_once()
    call_kwargs = mock_audit_instance.log.await_args.kwargs
    assert call_kwargs["action"] == "coordinator.replay_drift_detected"
    assert call_kwargs["details"]["jaccard"] < 0.6
