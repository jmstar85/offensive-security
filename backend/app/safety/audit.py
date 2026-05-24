"""Audit logger — records all orchestrator and safety actions to the DB.

PR-8 (kali coexistence) adds a typed schema for five new safety-subsystem
events emitted by the Kali path. Each schema names the required payload
fields so downstream consumers (Prometheus, dashboards, alerts) can rely on
a stable shape. ``KALI_AUDIT_EVENT_SCHEMAS`` is the public registry.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.observability.metrics import metrics


class AuditLogger:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        action: str,
        actor_id: str | None = None,
        target_entity: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        entry = AuditLog(
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            action=action,
            target_entity=target_entity,
            target_id=target_id,
            details_json=details,
            ip_address=ip_address,
        )
        self._db.add(entry)
        # Flush but don't commit — caller manages transaction
        await self._db.flush()


# --- Kali coexistence event schemas (PR-8) -----------------------------------

# Every emitter MUST populate these fields. Schemas are also exported so unit
# tests and the runbook stay in lock-step with the code.
_COMMON_FIELDS: frozenset[str] = frozenset({
    "tool_slug", "args", "reason", "step_id", "session_id", "timestamp",
})

KALI_AUDIT_EVENT_SCHEMAS: dict[str, frozenset[str]] = {
    "kali_exec.start": _COMMON_FIELDS | {"container_id"},
    "kali_exec.shim_block": _COMMON_FIELDS,
    "kali_exec.hardening_violation": _COMMON_FIELDS | {"container_id"},
    "kali_exec.filter_plan_steps_block": _COMMON_FIELDS,
    "kali_exec.tier_gate_block": _COMMON_FIELDS | {"required_flag"},
}


def emit_kali_metric(event: str, payload: dict[str, Any]) -> None:
    """Bump the Prometheus counter that corresponds to a kali audit event.

    Called by the safety-layer emitters (``audit_safety_event`` in
    ``kali_allowlist.py`` and the filter_plan_steps branch). The mapping is
    deliberately narrow — only events that have a registered counter trigger
    a metric increment.
    """
    if event == "kali_exec.start":
        metrics.kali_exec_total.inc(tool_slug=str(payload.get("tool_slug", "")), outcome="started")
    elif event == "kali_exec.shim_block":
        metrics.kali_shim_block_total.inc(reason=str(payload.get("reason", "unknown")))
    elif event == "kali_exec.hardening_violation":
        metrics.kali_container_start_failures_total.inc(reason=str(payload.get("reason", "unknown")))
    elif event == "kali_exec.filter_plan_steps_block":
        metrics.kali_filter_plan_block_total.inc(
            tool_slug=str(payload.get("slug") or payload.get("tool_slug") or "unknown"),
            reason=str(payload.get("reason", "unknown")),
        )
