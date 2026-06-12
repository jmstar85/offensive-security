"""LIVE differential replay harness for the PR2 ``PlanExecutor`` refactor.

This is the test the prior plan draft *falsely assumed already existed*. Unlike
``test_v11_byte_identical.py`` (which loads golden JSON fixtures and compares them
to themselves / poisoned copies and NEVER runs the live pipeline), this module
drives the REAL ``PlanExecutor.execute`` saved-workflow path twice against the
in-memory test DB, captures the emitted ``audit_log`` AND ``agent_execution`` rows
each time, and feeds them into the same v1.1 comparator functions.

Purpose: PR2 extracts ``execute_tool_through_safety_chain`` and refactors
``PlanExecutor.execute`` onto it. If that refactor mis-scopes the helper so an
``AgentExecution`` row-creation or finalization site moves (the trap both reviewers
flagged), this harness turns RED — the agent_execution row COUNT or creation-ORDER
diverges. ``agent_execution`` rows are NOT covered by ``EXCLUDED_AUDIT_PREFIXES``
(``v11_comparator.py:10-22`` only excludes ``audit_log`` *actions*), so this is the
real replay-exposure surface.

Authored to PASS against the PRE-refactor code, so it is a true before/after
differential when PR2 lands.
"""
from __future__ import annotations

import pytest

from tests._regression.v11_comparator import (
    assert_no_coordinator_in_saved_workflow_trace,
    compare_agent_execution_rows,
    compare_audit_log_rows,
)
from tests.regression._live_replay_harness import (
    SAVED_WORKFLOW_STEPS,
    run_saved_workflow_once,
)


@pytest.mark.asyncio
async def test_live_saved_workflow_audit_rows_are_deterministic(db):
    """Two live runs of the same saved workflow emit byte-identical audit_log rows.

    A PR2 refactor that perturbs ``PlanExecutor.execute``'s audit emission would
    make ``compare_audit_log_rows`` non-empty here.
    """
    run_a = await run_saved_workflow_once(db)
    run_b = await run_saved_workflow_once(db)

    diffs = compare_audit_log_rows(run_a["audit_rows"], run_b["audit_rows"])
    assert diffs == [], f"audit_log rows drifted across two live runs: {diffs}"


@pytest.mark.asyncio
async def test_live_saved_workflow_agent_execution_rows_are_deterministic(db):
    """Two live runs emit byte-identical agent_execution rows (slug, args,
    exit_code, findings, started_at) via the comparator."""
    run_a = await run_saved_workflow_once(db)
    run_b = await run_saved_workflow_once(db)

    diffs = compare_agent_execution_rows(
        run_a["agent_execution_rows"], run_b["agent_execution_rows"]
    )
    assert diffs == [], f"agent_execution rows drifted across two live runs: {diffs}"


@pytest.mark.asyncio
async def test_live_agent_execution_row_count_and_order_unchanged(db):
    """EXPLICIT count + creation-order assertion (the surface a mis-scoped helper
    perturbs). The comparator diffs positionally, but we assert count and the
    ordered slug sequence directly so a PR2 regression names exactly what moved.
    """
    run_a = await run_saved_workflow_once(db)
    run_b = await run_saved_workflow_once(db)

    rows_a = run_a["agent_execution_rows"]
    rows_b = run_b["agent_execution_rows"]

    # One agent_execution row per plan step, every run.
    assert len(rows_a) == len(SAVED_WORKFLOW_STEPS), (
        f"expected {len(SAVED_WORKFLOW_STEPS)} agent_execution rows, got {len(rows_a)}"
    )
    assert len(rows_a) == len(rows_b), (
        f"agent_execution row COUNT drifted: {len(rows_a)} != {len(rows_b)}"
    )

    # Creation ORDER (ORDER BY started_at, id) must match the plan-step order and
    # be identical across runs.
    order_a = [r["slug"] for r in rows_a]
    order_b = [r["slug"] for r in rows_b]
    expected_order = [s["agent"] for s in SAVED_WORKFLOW_STEPS]
    assert order_a == expected_order, (
        f"agent_execution creation order != plan order: {order_a} != {expected_order}"
    )
    assert order_a == order_b, (
        f"agent_execution creation ORDER drifted across runs: {order_a} != {order_b}"
    )

    # Every row finalized to 'completed' (no step silently dropped/failed).
    assert all(r["_status"] == "completed" for r in rows_a), (
        f"not all agent_execution rows completed: {[r['_status'] for r in rows_a]}"
    )


@pytest.mark.asyncio
async def test_live_saved_workflow_emits_no_coordinator_events(db):
    """The saved-workflow lane must never emit ``coordinator.*`` audit rows
    (the deterministic-replay no-coordinator invariant), asserted on LIVE rows."""
    run = await run_saved_workflow_once(db)
    assert_no_coordinator_in_saved_workflow_trace(run["audit_rows"])
