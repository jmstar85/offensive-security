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
from app.orchestrator.rescope_service import DiscoveredTarget, RescopeService
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

            # PR2b.3: harvest newly-discovered hosts from step findings and trigger
            # rescope automatically. Findings shaped as either:
            #   - {'new_hosts': [{'host': str, 'tier': str}], ...}  (preferred)
            #   - {'host': str, 'tier': str, 'is_new': True}        (per-finding)
            new_host_records: list[DiscoveredTarget] = []
            for f in step_findings:
                if not isinstance(f, dict):
                    continue
                # Shape A — explicit new_hosts list inside a single finding row
                for nh in (f.get("new_hosts") or []):
                    host = nh.get("host") if isinstance(nh, dict) else None
                    tier = (nh.get("tier") if isinstance(nh, dict) else None) or "passive_recon"
                    if host:
                        new_host_records.append(DiscoveredTarget(
                            host=host, tier=tier,
                            discovered_by_step_id=str(step.get("id") or step.get("order", "")),
                        ))
                # Shape B — finding row IS a discovered host
                if f.get("is_new") and f.get("host"):
                    new_host_records.append(DiscoveredTarget(
                        host=f["host"],
                        tier=f.get("tier", "passive_recon"),
                        discovered_by_step_id=str(step.get("id") or step.get("order", "")),
                    ))

            if new_host_records:
                rescope = RescopeService(self._db)
                try:
                    approval = await rescope.pause_for_rescope(
                        session_id=session_id,
                        discovered=new_host_records,
                        requesting_step_id=str(step.get("id") or step.get("order", "")),
                    )
                    if approval is not None:
                        # Session paused — emit a session_update so the UI swaps to
                        # the rescope-pending state, then stop iterating further
                        # steps. The orchestrator will pick up again when the
                        # operator decides via RescopeService.decide_rescope.
                        await event_bus.publish(str(session_id), {
                            "type": "session_update",
                            "status": "paused_for_rescope",
                            "rescope_id": str(approval.id),
                        }, topic="session")
                        return all_findings
                except Exception as exc:  # noqa: BLE001
                    # Rescope service raised — log + continue with already-approved
                    # scope. The egress monitor remains the authoritative gate.
                    await self._audit.log(
                        action="rescope_trigger_failed",
                        actor_id=actor_id,
                        target_entity="pentest_session",
                        target_id=str(session_id),
                        details={"error": str(exc)},
                    )

            await event_bus.publish(str(session_id), {
                "type": "agent_completed",
                "agent": agent_type,
                "execution_id": str(exec_id),
                "finding_count": len(step_findings),
            }, topic="tasks")

        return all_findings
