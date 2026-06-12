"""Shared LIVE differential replay harness — NOT a pytest test module.

This module drives the REAL saved-workflow pipeline (``PlanExecutor.execute``)
against the in-memory SQLite test DB with MOCKED tool adapters, and reads the
emitted ``audit_log`` and ``agent_execution`` rows back out of the DB in a shape
the v1.1 comparator (``tests/_regression/v11_comparator.py``) can diff.

It is imported by:
  * ``tests/regression/test_planexecutor_refactor_byte_identical.py``
  * ``tests/regression/test_deterministic_lane_unchanged_with_xbow_off.py``

Why drive ``PlanExecutor.execute`` directly rather than ``OrchestratorService.run``
end-to-end: ``PlanExecutor.execute`` is the *exact* surface the PR2 runtime-helper
refactor touches (row creation at ``executor.py:42-51``, finalization at
``:117-161``, the runtime brakes at ``:66-206``). Driving it directly with the
real async session lets us query the live ``agent_executions`` rows back and diff
their COUNT + creation-ORDER, which is the replay-exposure surface a mis-scoped
helper would perturb. ``OrchestratorService.run`` would additionally require a
seeded ``Project``/``Target`` graph and exercises the plan-time filter trio, which
is out of scope for *this* harness (the filter trio's cardinality is a separate
per-lane invariant covered by other PR4 tests). This is the documented fallback
the PR0 brief permits ("drive ``PlanExecutor.execute`` directly with a real async
session from the fixture").

The fake adapter is fully deterministic: it yields a fixed ``status`` (running),
a fixed ``log`` line, and a terminal ``status`` carrying a fixed ``findings``
list. No Docker, no network, no time-dependent payload — so two runs of the same
saved workflow are byte-identical by construction *unless* the executor's own
row/audit emission drifts.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentEvent
from app.models.audit import AuditLog
from app.models.session import AgentExecution
from app.orchestrator.executor import PlanExecutor


# ── Deterministic saved-workflow plan ────────────────────────────────────────

# Two recon steps with stable slugs/config. No new-host findings → no rescope
# pause, so the executor runs every step to completion every time. Findings are
# fixed so ``parsed_findings_canonical`` is stable across runs.
SAVED_WORKFLOW_STEPS: list[dict] = [
    {
        "agent": "nmap",
        "order": 1,
        "tier": "active_recon",
        "config": {"flags": "-sV", "tool_slug": "nmap"},
    },
    {
        "agent": "httpx",
        "order": 2,
        "tier": "passive_low_touch",
        "config": {"tool_slug": "httpx"},
    },
]

# Per-slug deterministic findings (no ``new_hosts`` / ``is_new`` → no rescope).
_FINDINGS_BY_AGENT: dict[str, list[dict]] = {
    "nmap": [{"type": "port", "port": 80, "service": "http", "severity": "low"}],
    "httpx": [{"type": "http", "status": 200, "title": "Example", "severity": "info"}],
}


def _make_fake_adapter(agent_type: str):
    """Return a fake adapter whose ``execute`` yields a fixed deterministic event
    stream: status(running) → log → status(completed, findings)."""
    findings = _FINDINGS_BY_AGENT.get(agent_type, [])

    class _FakeAdapter:
        async def execute(
            self,
            target: dict,
            config: dict,
            execution_id_out: list[str] | None = None,
        ) -> AsyncGenerator[AgentEvent, None]:
            # Deterministic container id so kill-registration writes a stable value.
            exec_id = f"container-{agent_type}"
            if execution_id_out is not None:
                execution_id_out.append(exec_id)
            yield AgentEvent("status", agent_type, exec_id, {"status": "running"})
            yield AgentEvent("log", agent_type, exec_id, {"line": f"{agent_type}: scanning target"})
            yield AgentEvent(
                "status",
                agent_type,
                exec_id,
                {"status": "completed", "result": {"findings": findings}},
            )

    return _FakeAdapter()


# ── Row capture / normalisation ──────────────────────────────────────────────

async def _audit_rows(db: AsyncSession, session_id: uuid.UUID) -> list[dict]:
    """Read audit_logs for the session, normalised into comparator row dicts,
    ordered by creation (created_at, id)."""
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.target_id == str(session_id))
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    rows: list[dict] = []
    for row in result.scalars().all():
        ts = getattr(row, "created_at", None)
        rows.append({
            "action": row.action,
            "target_entity": row.target_entity,
            "target_id": str(row.target_id) if row.target_id is not None else "",
            "details_json": row.details_json or {},
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else None,
        })
    return rows


async def _agent_execution_rows(db: AsyncSession, session_id: uuid.UUID) -> list[dict]:
    """Read agent_executions for the session in creation order, normalised into
    the ``compare_agent_execution_rows`` row shape.

    ``started_at`` is the creation-order anchor; we ORDER BY (started_at, id) so
    a refactor that reorders row creation surfaces as a positional diff.
    """
    result = await db.execute(
        select(AgentExecution)
        .where(AgentExecution.session_id == session_id)
        .order_by(AgentExecution.started_at, AgentExecution.id)
    )
    rows: list[dict] = []
    for row in result.scalars().all():
        output = row.output_json or {}
        findings = output.get("findings", []) if isinstance(output, dict) else []
        started = row.started_at
        rows.append({
            "slug": row.agent_type,
            "normalised_args": row.config_json or {},
            "exit_code": 0 if row.status == "completed" else 1,
            "parsed_findings_canonical": findings,
            "started_at": started.isoformat() if isinstance(started, datetime) else "",
            # Retained for explicit COUNT/ORDER assertions in the test (not used
            # by the comparator itself).
            "_status": row.status,
        })
    return rows


# ── Public driver ────────────────────────────────────────────────────────────

async def run_saved_workflow_once(
    db: AsyncSession,
    *,
    steps: list[dict] | None = None,
) -> dict:
    """Run ONE saved-workflow execution through the real ``PlanExecutor`` against
    the live test DB with mocked adapters, and return its captured row sets.

    Returns ``{"session_id", "findings", "audit_rows", "agent_execution_rows"}``.
    Each call uses a fresh ``session_id`` so successive runs do not collide in the
    shared in-memory DB — the comparator diffs the two captured row *sets*, and
    ``target_id`` UUIDs are normalised positionally by the comparator.
    """
    steps = steps if steps is not None else SAVED_WORKFLOW_STEPS
    session_id = uuid.uuid4()
    actor_id = str(uuid.uuid4())

    executor = PlanExecutor(db)

    def _fake_get_adapter(agent_type: str):
        return _make_fake_adapter(agent_type)

    # Patch the event bus so no real subscribers are required; we assert on DB
    # rows, not on published events, for replay determinism.
    # get_adapter now lives in the shared runtime helper (PR2); event_bus stays
    # in the executor (publishes are caller-owned).
    with patch("app.orchestrator.safety_exec.get_adapter", side_effect=_fake_get_adapter), \
         patch("app.orchestrator.executor.event_bus") as mock_bus:
        mock_bus.publish = AsyncMock()
        findings = await executor.execute(
            session_id=session_id,
            steps=[dict(s) for s in steps],  # defensive copy — executor mutates step dicts
            target={"ip_ranges": ["45.33.32.156"], "domains": ["scanme.nmap.org"]},
            whitelist_rules={"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]},
            actor_id=actor_id,
        )
        await db.flush()

    audit_rows = await _audit_rows(db, session_id)
    agent_execution_rows = await _agent_execution_rows(db, session_id)
    return {
        "session_id": session_id,
        "findings": findings,
        "audit_rows": audit_rows,
        "agent_execution_rows": agent_execution_rows,
    }
