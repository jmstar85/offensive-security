"""Plan executor — runs approved steps sequentially, streaming events."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kali_whitelist import SafetyViolation
from app.agents.registry import get_adapter
from app.core.events import event_bus
from app.models.session import AgentExecution
from app.safety.audit import AuditLogger
from app.safety.audit_kali import persist_kali_shim_block
from app.safety.egress_monitor import EgressMonitor


class PlanExecutor:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._audit = AuditLogger(db)

    async def execute(
        self,
        session_id: uuid.UUID,
        steps: list[dict],
        target: dict,
        whitelist_rules: dict,
        actor_id: str,
    ) -> list[dict]:
        """Execute all approved plan steps. Returns list of per-step results."""
        egress_monitor = EgressMonitor(session_id, whitelist_rules)
        all_findings: list[dict] = []

        for step in steps:
            agent_type = step["agent"]
            config = step.get("config", {})

            # Create execution record
            execution = AgentExecution(
                session_id=session_id,
                agent_type=agent_type,
                status="running",
                config_json=config,
                started_at=datetime.now(timezone.utc),
            )
            self._db.add(execution)
            await self._db.flush()
            exec_id = execution.id

            # v4.0 P4 gap-fill 3/3 — Tasks tab receives step-lifecycle events.
            await event_bus.publish(str(session_id), {
                "type": "agent_started",
                "agent": agent_type,
                "execution_id": str(exec_id),
                "step": step.get("order", 0),
            }, topic="tasks")

            adapter = get_adapter(agent_type)
            container_id_holder: list[str] = []
            step_findings: list[dict] = []

            try:
                async for event in adapter.execute(target, config, container_id_holder):
                    # Register container ID for kill switch
                    if container_id_holder and not execution.container_id:
                        execution.container_id = container_id_holder[0]
                        await self._db.execute(
                            update(AgentExecution)
                            .where(AgentExecution.id == exec_id)
                            .values(container_id=container_id_holder[0])
                        )

                    # Egress monitor on log lines
                    if event.event_type == "log":
                        line = event.data.get("line", "")
                        safe = await egress_monitor.monitor_log_line(line, actor_id)
                        if not safe:
                            return all_findings  # session killed

                    # v4.0 P4 gap-fill 3/3 — route per-event-type to the
                    # right panel topic. Logs go to the Terminal tab; status
                    # / finding / error go to the Agents tab. Legacy
                    # subscribers (no `topics` filter) still receive all
                    # events.
                    event_topic = (
                        "terminal" if event.event_type == "log" else "agents"
                    )
                    await event_bus.publish(str(session_id), {
                        "type": event.event_type,
                        "agent": event.agent_type,
                        "execution_id": str(exec_id),
                        "data": event.data,
                    }, topic=event_topic)

                    # Collect findings from final status event
                    if event.event_type == "status" and "result" in event.data:
                        result = event.data["result"]
                        step_findings = result.get("findings", [])

            except SafetyViolation as exc:
                # WhitelistShim rejected the (slug, args) pair at build_command
                # time. Persist the per-step row to audit_logs so operators
                # can see it in /audit-logs — the Python-logging + Prometheus
                # emission inside kali_allowlist alone is not UI-visible.
                if agent_type.startswith("kali_"):
                    await persist_kali_shim_block(
                        self._audit,
                        session_id=session_id,
                        actor_id=actor_id,
                        agent=agent_type,
                        tool_slug=config.get("tool_slug"),
                        reason=str(exc),
                    )
                await self._db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(
                        status="failed",
                        ended_at=datetime.now(timezone.utc),
                        output_json={"error": str(exc), "reason": "shim_block"},
                    )
                )
                await event_bus.publish(str(session_id), {
                    "type": "agent_failed",
                    "agent": agent_type,
                    "execution_id": str(exec_id),
                    "error": str(exc),
                    "reason": "shim_block",
                }, topic="tasks")
                continue
            except Exception as exc:
                await self._db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(
                        status="failed",
                        ended_at=datetime.now(timezone.utc),
                        output_json={"error": str(exc)},
                    )
                )
                await event_bus.publish(str(session_id), {
                    "type": "agent_failed",
                    "agent": agent_type,
                    "execution_id": str(exec_id),
                    "error": str(exc),
                }, topic="tasks")
                continue

            all_findings.extend(step_findings)
            await self._db.execute(
                update(AgentExecution)
                .where(AgentExecution.id == exec_id)
                .values(
                    status="completed",
                    ended_at=datetime.now(timezone.utc),
                    output_json={"findings": step_findings},
                )
            )
            await event_bus.publish(str(session_id), {
                "type": "agent_completed",
                "agent": agent_type,
                "execution_id": str(exec_id),
                "finding_count": len(step_findings),
            }, topic="tasks")

        return all_findings
