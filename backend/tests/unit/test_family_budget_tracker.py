from __future__ import annotations

import uuid
from unittest.mock import patch

from app.orchestrator.family_budget_tracker import FamilyBudgetTracker


def _tracker() -> FamilyBudgetTracker:
    return FamilyBudgetTracker()


def test_record_then_get_returns_total():
    t = _tracker()
    sid = uuid.uuid4()
    t.record(sid, "recon", 100)
    t.record(sid, "recon", 50)
    assert t.get(sid, "recon") == 150


def test_snapshot_returns_all_families_for_session():
    t = _tracker()
    sid = uuid.uuid4()
    t.record(sid, "recon", 10)
    t.record(sid, "exploit", 20)
    t.record(sid, "extraction", 30)
    snap = t.snapshot(sid)
    assert snap == {"recon": 10, "exploit": 20, "extraction": 30}


def test_separate_sessions_isolated():
    t = _tracker()
    sid1 = uuid.uuid4()
    sid2 = uuid.uuid4()
    t.record(sid1, "recon", 100)
    t.record(sid2, "recon", 200)
    assert t.get(sid1, "recon") == 100
    assert t.get(sid2, "recon") == 200
    snap1 = t.snapshot(sid1)
    snap2 = t.snapshot(sid2)
    assert snap1 == {"recon": 100}
    assert snap2 == {"recon": 200}


def test_record_increments_prometheus_counter():
    from app.observability.metrics import metrics

    t = _tracker()
    sid = uuid.uuid4()
    before = metrics.family_tokens_total.value(session_id=str(sid), family_kind="exploit")
    t.record(sid, "exploit", 75)
    after = metrics.family_tokens_total.value(session_id=str(sid), family_kind="exploit")
    assert after == before + 75


def test_get_for_missing_family_returns_zero():
    t = _tracker()
    sid = uuid.uuid4()
    assert t.get(sid, "nonexistent") == 0
