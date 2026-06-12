"""Deterministic lane stays byte-identical-green when every ``osa_*`` flag is OFF.

With all the autonomous/XBOW feature flags at their default ``False``, the live
deterministic ``PlanExecutor`` pipeline must:
  1. emit ``audit_log`` + ``agent_execution`` rows that are stable across runs, and
  2. leak NO autonomous/coordinator rows into the trace —
     no ``coordinator.*`` (``assert_no_coordinator_in_saved_workflow_trace``) and
     no ``agent_family.*`` (the autonomous family-materialisation prefix).

``agent_execution`` rows are NOT covered by ``EXCLUDED_AUDIT_PREFIXES``
(``v11_comparator.py:10-22`` excludes only ``audit_log`` *actions*), so flag-gating
is their ONLY protection — an autonomous lane accidentally enabled by a flag-default
regression would surface its extra ``AgentExecution`` rows here.

Reuses the live differential harness from
``tests/regression/_live_replay_harness.py`` (same real-pipeline driver as
``test_planexecutor_refactor_byte_identical.py``).
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from tests._regression.v11_comparator import (
    assert_no_coordinator_in_saved_workflow_trace,
    compare_agent_execution_rows,
    compare_audit_log_rows,
)
from tests.regression._live_replay_harness import run_saved_workflow_once

# The osa_* flags that, if ON, would route execution onto an autonomous/XBOW
# lane and could leak coordinator / agent_family / autonomous agent_execution
# rows into the deterministic trace.
_XBOW_FLAGS = (
    "osa_coordinator_enabled",
    "osa_coordinator_replay_enabled",
    "osa_coordinator_populate_on_replay",
    "osa_xbow_families_enabled",
    "osa_kali_backend_enabled",
    "osa_multi_provider_llm",
)


def test_all_xbow_flags_default_off():
    """Guard the precondition: every autonomous/XBOW flag defaults to False.

    If a default flips to True, the deterministic-lane byte-identical guarantee
    (and the rest of this file's assertions) silently stops meaning what it says,
    so fail loudly here first.
    """
    for flag in _XBOW_FLAGS:
        assert getattr(settings, flag) is False, (
            f"expected settings.{flag} to default to False; got {getattr(settings, flag)!r}"
        )
    # Provider stays on the deterministic/anthropic default (no ollama loop).
    assert settings.osa_llm_provider == "anthropic", (
        f"expected osa_llm_provider default 'anthropic'; got {settings.osa_llm_provider!r}"
    )


@pytest.mark.asyncio
async def test_deterministic_audit_and_agent_execution_rows_stable_with_flags_off(db):
    """With flags OFF, two live deterministic runs are byte-identical in BOTH
    audit_log and agent_execution rows."""
    run_a = await run_saved_workflow_once(db)
    run_b = await run_saved_workflow_once(db)

    audit_diffs = compare_audit_log_rows(run_a["audit_rows"], run_b["audit_rows"])
    assert audit_diffs == [], f"audit_log drifted with flags off: {audit_diffs}"

    exec_diffs = compare_agent_execution_rows(
        run_a["agent_execution_rows"], run_b["agent_execution_rows"]
    )
    assert exec_diffs == [], f"agent_execution drifted with flags off: {exec_diffs}"


@pytest.mark.asyncio
async def test_no_autonomous_or_coordinator_rows_leak_with_flags_off(db):
    """No coordinator.* and no agent_family.* rows appear in the deterministic
    trace, and every agent_execution row belongs to a deterministic plan step."""
    run = await run_saved_workflow_once(db)

    # coordinator.* invariant.
    assert_no_coordinator_in_saved_workflow_trace(run["audit_rows"])

    # agent_family.* (autonomous family materialisation) must not appear.
    family_rows = [
        r for r in run["audit_rows"]
        if str(r.get("action", "")).startswith("agent_family.")
    ]
    assert family_rows == [], (
        f"autonomous agent_family.* rows leaked into deterministic trace: "
        f"{[r['action'] for r in family_rows]}"
    )

    # agent_execution rows are flag-gated only (NOT excluded by the comparator):
    # every row here must be a deterministic plan-step slug, never an autonomous
    # family/role slug.
    autonomous_slugs = {"session_management_agent", "discovery_agent", "attack_agent"}
    leaked = [
        r for r in run["agent_execution_rows"]
        if r["slug"] in autonomous_slugs
    ]
    assert leaked == [], (
        f"autonomous agent_execution rows leaked with flags off: "
        f"{[r['slug'] for r in leaked]}"
    )
