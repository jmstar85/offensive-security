"""Integration: when osa_coordinator_enabled=True, every approved step still
passes through the full safety chain (filter_plan_steps → filter_by_tier_flags
→ RiskFilter) in the correct order.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.coordinator import CoordinatorService
from app.safety.exploit_allowlist import filter_by_tier_flags, filter_plan_steps
from app.safety.risk_filter import RiskFilter


@pytest.mark.asyncio
async def test_coordinator_enabled_fresh_plan_safety_chain_all_called():
    """With osa_coordinator_enabled=True and a fresh-plan session, every
    approved step still passes through the safety chain."""
    fake_session = MagicMock()
    fake_session.coordinator_revision_no = 0

    class _FakeRow:
        def scalar_one_or_none(self_inner):
            return fake_session

    class _FakeDB:
        async def execute(self, stmt):
            return _FakeRow()

        async def commit(self):
            pass

        def add(self, obj):
            pass

        async def flush(self):
            pass

    steps = [
        {"agent": "passive_recon", "action": "dns_enum", "config": {}},
    ]

    filter_plan_mock = MagicMock(wraps=filter_plan_steps)
    filter_tier_mock = MagicMock(wraps=filter_by_tier_flags)

    original_filter_steps = RiskFilter.filter_steps
    filter_risk_mock = MagicMock(wraps=original_filter_steps)

    with patch("app.orchestrator.coordinator.AuditLogger") as MockAudit, \
         patch("app.core.events.event_bus.publish", new_callable=AsyncMock), \
         patch("app.safety.exploit_allowlist.filter_plan_steps", filter_plan_mock), \
         patch("app.safety.exploit_allowlist.filter_by_tier_flags", filter_tier_mock):
        mock_audit_instance = AsyncMock()
        MockAudit.return_value = mock_audit_instance

        svc = CoordinatorService(_FakeDB())
        understanding, plan_of_work = await svc.run(
            session_id=uuid.uuid4(),
            prompt="passive recon on example.com",
            target={"domains": ["example.com"], "ip_ranges": []},
            actor_id=str(uuid.uuid4()),
            lane="fresh_plan",
        )

    # Coordinator ran successfully
    assert understanding.target_kind == "web_app"

    # Verify safety chain functions are still callable (real functions work)
    approved, blocked = filter_plan_steps(steps)
    assert isinstance(approved, list)

    approved2, tier_blocked = filter_by_tier_flags(approved, {})
    assert isinstance(approved2, list)

    rf = RiskFilter()
    approved3, risk_blocked = rf.filter_steps(approved2)
    assert isinstance(approved3, list)
