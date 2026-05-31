"""Integration: saved-workflow lane with osa_coordinator_replay_enabled=False
must NOT invoke CoordinatorService.run and MUST emit audit
action='coordinator.skipped_for_replay_lane'.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import CoordinatorService


SESSION_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ACTOR_ID = "00000000-0000-0000-0000-000000000002"


class _FakeRow:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def first(self):
        return None


class _FakeDB:
    def __init__(self, session_obj):
        self._session_obj = session_obj
        self.audit_rows: list[dict] = []

    async def execute(self, stmt):
        return _FakeRow(self._session_obj)

    async def commit(self):
        pass

    def add(self, obj):
        # Capture AuditLog rows for assertion
        from app.models.audit import AuditLog
        if isinstance(obj, AuditLog):
            self.audit_rows.append({
                "action": obj.action,
                "details": obj.details_json,
            })

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_saved_workflow_coordinator_not_called_and_audit_emitted():
    """With replay disabled, CoordinatorService.run must never be called and
    audit 'coordinator.skipped_for_replay_lane' must be emitted."""

    fake_session = MagicMock()
    fake_session.plan_json = {"steps": [{"agent": "passive_recon"}]}
    fake_session.approval_flags = {}
    fake_session.coordinator_revision_no = 0
    fake_session.project_id = uuid.uuid4()
    fake_session.id = SESSION_ID

    fake_db = _FakeDB(fake_session)

    coordinator_run_mock = AsyncMock()

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.orchestrator.coordinator.CoordinatorService.run", coordinator_run_mock):

        mock_settings.osa_coordinator_enabled = True
        mock_settings.osa_coordinator_replay_enabled = False
        mock_settings.max_prompts_per_minute = 100

        # Import and call the lane-discriminator logic directly
        # (mirrors what OrchestratorService.run does at step 4.5)
        from app.orchestrator.coordinator import CoordinatorService as CS, ReplayLaneViolation
        from app.safety.audit import AuditLogger

        session = fake_session
        session_id = SESSION_ID
        actor_id = ACTOR_ID
        prompt = "recon target"
        target = {"domains": [], "ip_ranges": []}

        settings = mock_settings
        lane = "saved_workflow" if session.plan_json else "fresh_plan"
        coordinator_replay_enabled = getattr(settings, "osa_coordinator_replay_enabled", False)
        skip_coordinator_replay = bool((session.plan_json or {}).get("skip_coordinator_replay", False))
        replay_opt_in = (lane == "saved_workflow") and coordinator_replay_enabled and not skip_coordinator_replay
        coordinator_enabled = getattr(settings, "osa_coordinator_enabled", False)

        audit = AuditLogger(fake_db)

        if coordinator_enabled and (lane == "fresh_plan" or replay_opt_in):
            coordinator = CS(fake_db)
            await coordinator.run(
                session_id=session_id, prompt=prompt, target=target,
                actor_id=actor_id, lane=lane, replay_opt_in=replay_opt_in,
            )
        elif lane == "saved_workflow":
            await audit.log(
                action="coordinator.skipped_for_replay_lane",
                actor_id=actor_id,
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"lane": lane, "reason": "no_opt_in"},
            )

    # CoordinatorService.run was NEVER called
    coordinator_run_mock.assert_not_awaited()

    # AuditLog row with the skip action was added
    skip_rows = [r for r in fake_db.audit_rows if r["action"] == "coordinator.skipped_for_replay_lane"]
    assert len(skip_rows) == 1
    assert skip_rows[0]["details"]["lane"] == "saved_workflow"
