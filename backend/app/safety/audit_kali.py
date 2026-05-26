"""DB-persistence for kali_exec.* safety events (fix #D).

``audit_safety_event`` in ``kali_allowlist`` already emits to Python
logging and bumps Prometheus counters, but those signals are not visible
to operators in the ``/audit-logs`` UI. This helper writes one row per
blocked kali step into the ``audit_logs`` table via the same
``AuditLogger`` that the rest of the orchestrator uses, so the chain of
"why was this step dropped?" stays end-to-end queryable from the
existing audit-logs page.

Scope choice: we persist only ``kali_*`` blocks per-step. Non-kali
blocked steps are still summarised by the orchestrator's existing
single ``"steps_blocked"`` row — they don't carry per-slug semantics
worth one row each yet.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from app.safety.audit import AuditLogger

ACTION_FILTER_PLAN = "kali_exec.filter_plan_steps_block"
ACTION_TIER_GATE = "kali_exec.tier_gate_block"
ACTION_SHIM_BLOCK = "kali_exec.shim_block"


def _is_kali(step: dict) -> bool:
    return str(step.get("agent", "")).startswith("kali_")


def _details(step: dict) -> dict:
    cfg = step.get("config") or {}
    return {
        "agent": step.get("agent"),
        "tool_slug": cfg.get("tool_slug"),
        "tier": step.get("tier"),
        "block_reason": step.get("block_reason"),
    }


async def persist_kali_shim_block(
    audit: AuditLogger,
    *,
    session_id: uuid.UUID,
    actor_id: str,
    agent: str,
    tool_slug: str | None,
    reason: str,
) -> None:
    """Record a call-time WhitelistShim rejection in the audit_logs table.

    Companion to ``audit_safety_event("kali_exec.shim_block", ...)``: that
    function logs to stdout and bumps a Prometheus counter, but only this
    DB row makes the rejection visible to operators in /audit-logs.
    Called from PlanExecutor when KaliExecAdapter.build_command raises
    SafetyViolation.
    """
    await audit.log(
        action=ACTION_SHIM_BLOCK,
        actor_id=actor_id,
        target_entity="pentest_session",
        target_id=str(session_id),
        details={
            "agent": agent,
            "tool_slug": tool_slug,
            "reason": reason,
        },
    )


async def persist_kali_blocked_steps(
    audit: AuditLogger,
    *,
    session_id: uuid.UUID,
    actor_id: str,
    plan_blocked: Sequence[dict],
    tier_blocked: Sequence[dict],
) -> int:
    """Insert one row per blocked kali step. Returns the count for tests."""
    n = 0
    for step in plan_blocked:
        if not _is_kali(step):
            continue
        await audit.log(
            action=ACTION_FILTER_PLAN,
            actor_id=actor_id,
            target_entity="pentest_session",
            target_id=str(session_id),
            details=_details(step),
        )
        n += 1
    for step in tier_blocked:
        if not _is_kali(step):
            continue
        await audit.log(
            action=ACTION_TIER_GATE,
            actor_id=actor_id,
            target_entity="pentest_session",
            target_id=str(session_id),
            details=_details(step),
        )
        n += 1
    return n
