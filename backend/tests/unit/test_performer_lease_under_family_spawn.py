"""Unit tests for _FamilyLease per-family concurrency sub-cap (SF-CRITIC-6)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import app.orchestrator.performer as performer_module
from app.orchestrator.performer import (
    FamilyConcurrencyLimit,
    Performer,
    PerformerConcurrencyLimit,
    _FamilyLease,
    _PerformerLease,
    _family_active_counts,
)


@pytest.fixture(autouse=True)
def reset_family_counts():
    """Clear module-level family state before each test."""
    performer_module._family_active_counts.clear()
    performer_module._active_performers.clear()
    yield
    performer_module._family_active_counts.clear()
    performer_module._active_performers.clear()


def make_performer() -> Performer:
    return Performer(db=MagicMock(), session_id=uuid4())


# ---------------------------------------------------------------------------
# test_family_lease_default_capacity_is_4
# ---------------------------------------------------------------------------

def test_family_lease_default_capacity_is_4():
    async def _run():
        p = make_performer()
        leases = []
        for _ in range(4):
            lease = p._family_concurrency_guard("recon")
            await lease.__aenter__()
            leases.append(lease)

        with pytest.raises(FamilyConcurrencyLimit):
            extra = p._family_concurrency_guard("recon")
            await extra.__aenter__()

        for lease in leases:
            await lease.__aexit__(None, None, None)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# test_family_lease_hard_ceiling_is_8
# ---------------------------------------------------------------------------

def test_family_lease_hard_ceiling_is_8():
    sid = uuid4()
    with pytest.raises(ValueError, match="SF-CRITIC-6"):
        _FamilyLease(sid, "recon", max_concurrent=9)


# ---------------------------------------------------------------------------
# test_family_lease_release_frees_slot
# ---------------------------------------------------------------------------

def test_family_lease_release_frees_slot():
    async def _run():
        p = make_performer()
        leases = []
        for _ in range(4):
            lease = p._family_concurrency_guard("recon")
            await lease.__aenter__()
            leases.append(lease)

        # Release one
        await leases[0].__aexit__(None, None, None)

        # Should now succeed
        new_lease = p._family_concurrency_guard("recon")
        await new_lease.__aenter__()
        await new_lease.__aexit__(None, None, None)

        for lease in leases[1:]:
            await lease.__aexit__(None, None, None)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# test_family_lease_separate_families_have_separate_caps
# ---------------------------------------------------------------------------

def test_family_lease_separate_families_have_separate_caps():
    async def _run():
        p = make_performer()
        recon_leases = []
        for _ in range(4):
            lease = p._family_concurrency_guard("recon")
            await lease.__aenter__()
            recon_leases.append(lease)

        # exploit is a different family — should still have room for 4
        exploit_leases = []
        for _ in range(4):
            lease = p._family_concurrency_guard("exploit")
            await lease.__aenter__()
            exploit_leases.append(lease)

        # 5th exploit should fail
        with pytest.raises(FamilyConcurrencyLimit):
            extra = p._family_concurrency_guard("exploit")
            await extra.__aenter__()

        for lease in recon_leases + exploit_leases:
            await lease.__aexit__(None, None, None)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# test_family_lease_separate_sessions_have_separate_caps
# ---------------------------------------------------------------------------

def test_family_lease_separate_sessions_have_separate_caps():
    async def _run():
        p1 = make_performer()
        p2 = make_performer()

        leases_p1 = []
        for _ in range(4):
            lease = p1._family_concurrency_guard("recon")
            await lease.__aenter__()
            leases_p1.append(lease)

        # p2 is a different session — its recon cap is independent
        leases_p2 = []
        for _ in range(4):
            lease = p2._family_concurrency_guard("recon")
            await lease.__aenter__()
            leases_p2.append(lease)

        # p1 recon should still be capped
        with pytest.raises(FamilyConcurrencyLimit):
            extra = p1._family_concurrency_guard("recon")
            await extra.__aenter__()

        for lease in leases_p1 + leases_p2:
            await lease.__aexit__(None, None, None)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# test_per_session_outer_lease_still_enforced
# ---------------------------------------------------------------------------

def test_per_session_outer_lease_still_enforced(monkeypatch):
    async def _run():
        # Force max_concurrent_performer_sessions to 1 so we can hit the cap
        from app.core.config import settings
        original = settings.max_concurrent_performer_sessions
        monkeypatch.setattr(settings, "max_concurrent_performer_sessions", 1)

        sid1 = uuid4()
        lease1 = _PerformerLease(sid1)
        await lease1.__aenter__()

        sid2 = uuid4()
        lease2 = _PerformerLease(sid2)
        with pytest.raises(PerformerConcurrencyLimit):
            await lease2.__aenter__()

        await lease1.__aexit__(None, None, None)

    asyncio.run(_run())
