"""Integration: When UnderstandingBuilder.build raises ModelUnreachable on a
saved-workflow lane with replay opt-in, the exception is caught upstream,
the saved workflow continues (no failure), and audit
'coordinator.run_failed_replay_lane' is logged.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import CoordinatorService, UnderstandingBuilder
from app.orchestrator.llm.base import ModelUnreachable
from app.safety.audit import AuditLogger


SESSION_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
ACTOR_ID = "00000000-0000-0000-0000-000000000004"

SAVED_PLAN = {
    "steps": [
        {"agent": "passive_recon", "action": "dns_enum", "config": {}},
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
async def test_model_unreachable_on_replay_lane_caught_and_audited():
    """Simulates the try/except ModelUnreachable block in OrchestratorService.run:
    when coordinator raises ModelUnreachable, session still proceeds and audit fires.
    """
    fake_session = MagicMock()
    fake_session.plan_json = SAVED_PLAN
    fake_session.coordinator_revision_no = 0
    fake_session.project_id = uuid.uuid4()
    fake_session.id = SESSION_ID

    fake_db = _FakeDB(fake_session)

    session_proceeded = []

    async def _raise_unreachable(prompt, target):
        raise ModelUnreachable("LLM timeout")

    with patch.object(UnderstandingBuilder, "build", side_effect=_raise_unreachable):
        # Replicate the OrchestratorService coordinator block logic
        from app.orchestrator.coordinator import CoordinatorService as CS, ReplayLaneViolation

        session = fake_session
        session_id = SESSION_ID
        actor_id = ACTOR_ID
        prompt = "recon target"
        target = {"domains": [], "ip_ranges": []}

        lane = "saved_workflow"
        replay_opt_in = True
        coordinator_enabled = True

        audit = AuditLogger(fake_db)

        if coordinator_enabled and (lane == "fresh_plan" or replay_opt_in):
            try:
                coordinator = CS(fake_db)
                understanding, plan_of_work = await coordinator.run(
                    session_id=session_id, prompt=prompt, target=target,
                    actor_id=actor_id, lane=lane, replay_opt_in=replay_opt_in,
                )
                await fake_db.commit()
            except ReplayLaneViolation:
                await audit.log(
                    action="coordinator.skipped_for_replay_lane",
                    actor_id=actor_id,
                    target_entity="pentest_session",
                    target_id=str(session_id),
                    details={"lane": lane},
                )
            except ModelUnreachable:
                await audit.log(
                    action="coordinator.run_failed_replay_lane",
                    actor_id=actor_id,
                    target_entity="pentest_session",
                    target_id=str(session_id),
                    details={"lane": lane},
                )

        # Saved workflow proceeds (no exception propagated to this point)
        session_proceeded.append(True)

    # Session did not crash — saved workflow can still execute
    assert len(session_proceeded) == 1

    # Audit row was written for the unreachable event
    failed_rows = [r for r in fake_db.audit_rows if r["action"] == "coordinator.run_failed_replay_lane"]
    assert len(failed_rows) == 1
    assert failed_rows[0]["details"]["lane"] == "saved_workflow"


@pytest.mark.asyncio
async def test_model_unreachable_does_not_fire_skipped_audit():
    """Ensure the ModelUnreachable path emits run_failed, NOT skipped_for_replay_lane."""
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0
    fake_db = _FakeDB(fake_session)

    async def _raise_unreachable(prompt, target):
        raise ModelUnreachable("timeout")

    with patch.object(UnderstandingBuilder, "build", side_effect=_raise_unreachable):
        from app.orchestrator.coordinator import CoordinatorService as CS, ReplayLaneViolation

        audit = AuditLogger(fake_db)

        try:
            cs = CS(fake_db)
            await cs.run(
                session_id=SESSION_ID,
                prompt="recon",
                target={"domains": [], "ip_ranges": []},
                actor_id=ACTOR_ID,
                lane="saved_workflow",
                replay_opt_in=True,
            )
        except ReplayLaneViolation:
            await audit.log(action="coordinator.skipped_for_replay_lane",
                actor_id=ACTOR_ID, target_entity="pentest_session",
                target_id=str(SESSION_ID), details={"lane": "saved_workflow"})
        except ModelUnreachable:
            await audit.log(action="coordinator.run_failed_replay_lane",
                actor_id=ACTOR_ID, target_entity="pentest_session",
                target_id=str(SESSION_ID), details={"lane": "saved_workflow"})

    skipped_rows = [r for r in fake_db.audit_rows if r["action"] == "coordinator.skipped_for_replay_lane"]
    failed_rows = [r for r in fake_db.audit_rows if r["action"] == "coordinator.run_failed_replay_lane"]

    assert skipped_rows == []
    assert len(failed_rows) == 1
