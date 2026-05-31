"""Regression tests: v1.1 byte-identical comparator + saved-workflow no-coordinator invariant."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tests._regression.v11_comparator import (
    EXCLUDED_AUDIT_PREFIXES,
    assert_no_coordinator_in_saved_workflow_trace,
    compare_audit_log_rows,
    is_excluded_action,
)

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "_regression" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    data = json.loads((_FIXTURES_DIR / name).read_text())
    return data["rows"]


def _bump_timestamp(ts: str, delta_ms: int) -> str:
    from datetime import datetime, timedelta, timezone
    s = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    dt2 = dt + timedelta(milliseconds=delta_ms)
    return dt2.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt2.microsecond // 1000:03d}Z"


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_comparator_byte_identical_with_self():
    for fixture_name in ("golden_fresh_plan.json", "golden_saved_workflow.json", "golden_mixed.json"):
        rows = _load_fixture(fixture_name)
        diffs = compare_audit_log_rows(rows, rows)
        assert diffs == [], f"{fixture_name}: expected empty diff, got {diffs}"


def test_comparator_detects_timestamp_drift_within_tolerance():
    rows = _load_fixture("golden_fresh_plan.json")
    bumped_10 = copy.deepcopy(rows)
    bumped_10[0]["timestamp"] = _bump_timestamp(bumped_10[0]["timestamp"], 10)
    diffs_10 = compare_audit_log_rows(bumped_10, rows, tolerance_ms=50)
    assert diffs_10 == [], f"10ms drift should be within 50ms tolerance; got {diffs_10}"

    bumped_200 = copy.deepcopy(rows)
    bumped_200[0]["timestamp"] = _bump_timestamp(bumped_200[0]["timestamp"], 200)
    diffs_200 = compare_audit_log_rows(bumped_200, rows, tolerance_ms=50)
    assert len(diffs_200) > 0, "200ms drift should exceed 50ms tolerance"
    assert any("timestamp" in d or "drift" in d for d in diffs_200), (
        f"diff should mention timestamp drift; got {diffs_200}"
    )


def test_comparator_detects_action_change():
    rows = _load_fixture("golden_fresh_plan.json")
    modified = copy.deepcopy(rows)
    original_action = modified[0]["action"]
    modified[0]["action"] = "session.CHANGED"
    diffs = compare_audit_log_rows(modified, rows)
    assert len(diffs) > 0, "changed action should produce a diff"
    assert any(original_action in d or "CHANGED" in d or "action" in d for d in diffs), (
        f"diff should name the changed action; got {diffs}"
    )


def test_saved_workflow_golden_has_no_coordinator_events():
    rows = _load_fixture("golden_saved_workflow.json")
    assert_no_coordinator_in_saved_workflow_trace(rows)


def test_assertion_fires_on_synthetic_violation():
    rows = _load_fixture("golden_saved_workflow.json")
    poisoned = copy.deepcopy(rows)
    poisoned.append({
        "action": "coordinator.run",
        "target_entity": "coordinator",
        "target_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "details_json": {"injected": True},
        "timestamp": "2026-05-31T11:01:00.000Z",
    })
    with pytest.raises(AssertionError, match="coordinator\\."):
        assert_no_coordinator_in_saved_workflow_trace(poisoned)


def test_excluded_action_set_complete():
    required = (
        "coordinator.",
        "agent_family.",
        "mitm_exec.",
        "headless_exec.",
        "oob.",
        "conversation.",
        "raw_conversation.",
        "credential_",
        "infra.network_membership_violation",
        "admin.enrich_understanding",
        "llm.provider_call",
    )
    for prefix in required:
        assert prefix in EXCLUDED_AUDIT_PREFIXES, (
            f"EXCLUDED_AUDIT_PREFIXES missing required entry: {prefix!r}"
        )
