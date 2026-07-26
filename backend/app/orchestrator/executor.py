"""Plan executor — runs approved steps sequentially, streaming events.

The per-step container run + live runtime brakes (adapter.execute, egress monitor,
container-id kill registration, shim-block audit) are delegated to the shared
``execute_tool_through_safety_chain`` helper (the single sanctioned adapter-execute
call site). This module keeps the ``AgentExecution`` row lifecycle, the topic
publishes, and the rescope harvest in place so the saved-workflow trace stays
byte-identical (see ``app/orchestrator/safety_exec.py`` for the boundary rationale).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import event_bus
from app.models.msgchain import MsgChain
from app.models.session import AgentExecution
from app.orchestrator.rescope_service import DiscoveredTarget, RescopeService
from app.orchestrator.safety_exec import execute_tool_through_safety_chain
from app.orchestrator.terminal_sink import TerminalLineSink
from app.safety.audit import AuditLogger
from app.safety.egress_monitor import EgressMonitor


def _summarize_findings(findings: list) -> str:
    """A short, human-readable bullet summary of a step's findings for the
    Agents-tab narration (tolerant of the varied per-tool finding shapes)."""
    if not findings:
        return ""
    lines: list[str] = []
    for f in findings[:5]:
        if not isinstance(f, dict):
            continue
        label = (
            f.get("name") or f.get("template_id") or f.get("service")
            or f.get("type") or f.get("port") or "finding"
        )
        detail = f.get("severity") or f.get("url") or f.get("host") or f.get("port") or ""
        lines.append(f"• {label} {detail}".rstrip())
    remaining = len(findings) - len(lines)
    if remaining > 0:
        lines.append(f"…and {remaining} more")
    return "\n" + "\n".join(lines) if lines else ""


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
            # Attach a Docker network so the tool container can reach the target.
            # Without this the backend runs with network_disabled=True and the scan
            # reaches nothing (host "up" via -Pn but 0 ports in ~0.1s, plus
            # "Unable to determine any DNS servers"). The autonomous Performer already
            # does this (performer.py); the saved_workflow / template lane (this
            # PlanExecutor) needs the same default so its tools can reach the target.
            config.setdefault("network", settings.osa_agent_container_network)

            # Create execution record
            execution = AgentExecution(
                session_id=session_id,
                agent_type=agent_type,
                status="running",
                config_json=config,
                started_at=datetime.now(timezone.utc),
                step_order=step.get("order"),
            )
            self._db.add(execution)
            await self._db.flush()
            exec_id = execution.id

            # migration 013: per-step buffer that persists streamed stdout to
            # terminal_lines so the /flow Terminal panel REPLAYS on reload. A
            # fresh sink per step keeps seq DB-derived + monotonic across steps.
            terminal_sink = TerminalLineSink(self._db, session_id)

            # v4.0 P4 gap-fill 3/3 — Tasks tab receives step-lifecycle events.
            await event_bus.publish(str(session_id), {
                "type": "agent_started",
                "agent": agent_type,
                "execution_id": str(exec_id),
                "step": {"order": step.get("order", 0), "status": "running"},
            }, topic="tasks")

            # Caller-owned sinks the runtime helper calls mid-stream. Loop vars are
            # bound as defaults so each step's closure captures its own row/exec_id.
            async def _register_container(
                container_id: str,
                _execution: AgentExecution = execution,
                _exec_id: uuid.UUID = exec_id,
            ) -> None:
                # Register container ID for the kill switch (it reads
                # AgentExecution.container_id) — once, on the first event.
                if not _execution.container_id:
                    _execution.container_id = container_id
                    await self._db.execute(
                        update(AgentExecution)
                        .where(AgentExecution.id == _exec_id)
                        .values(container_id=container_id)
                    )

            async def _publish_event(
                event,
                _exec_id: uuid.UUID = exec_id,
                _sink: TerminalLineSink = terminal_sink,
            ) -> None:
                # v4.0 P4 gap-fill 3/3 — route per-event-type to the right panel
                # topic. Logs go to the Terminal tab; status / finding / error go to
                # the Agents tab. Legacy subscribers (no `topics` filter) still
                # receive all events.
                event_topic = "terminal" if event.event_type == "log" else "agents"
                payload = {
                    "type": event.event_type,
                    "agent": event.agent_type,
                    "execution_id": str(_exec_id),
                    "data": event.data,
                }
                # migration 013: persist stdout so the Terminal panel REPLAYS on
                # reload; carry the assigned per-session `seq` at the top level so
                # the frontend de-dupes the history/live boundary.
                if event.event_type == "log":
                    seq = await _sink.add(
                        execution_id=_exec_id,
                        agent_type=event.agent_type,
                        line=event.data.get("line", ""),
                    )
                    if seq is not None:
                        payload["seq"] = seq
                elif event.event_type == "status" and event.data.get("status") in (
                    "completed",
                    "failed",
                ):
                    # Terminal status for this step — flush the buffered remainder.
                    await _sink.flush()
                await event_bus.publish(str(session_id), payload, topic=event_topic)

            # Run the tool through the shared runtime safety envelope (the single
            # sanctioned adapter.execute site + egress/kill-reg/shim-audit brakes).
            result = await execute_tool_through_safety_chain(
                step,
                target,
                egress_monitor=egress_monitor,
                audit=self._audit,
                session_id=session_id,
                actor_id=actor_id,
                on_event=_publish_event,
                on_container_id=_register_container,
            )
            # Flush any buffered stdout tail (the killed / error paths never emit a
            # terminal status event). Defensive — never raises.
            await terminal_sink.flush()

            # Narrate this step into a MsgChain so the Agents tab shows a
            # conversational, per-sub-agent record on the DETERMINISTIC lane too —
            # not only on the autonomous Performer lane (which the Agents tab was
            # originally wired to). Runs before the row-finalization branches so a
            # killed/failed/timed-out step is narrated too.
            await self._narrate_step(session_id, step, config, execution.started_at, result)

            if result.killed:
                return all_findings  # session killed by egress monitor

            if result.egress_violation is not None:
                # Step-scope egress: the safety helper already stopped THIS step's
                # container. Finalize this step failed + CONTINUE — the remaining
                # in-scope steps still run (one benign off-scope fetch no longer
                # aborts the whole engagement). Escalation to a full session kill
                # (exploit-tier / cap) surfaces as result.killed above instead.
                await self._db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(
                        status="failed",
                        ended_at=datetime.now(timezone.utc),
                        output_json={
                            "error": result.egress_violation,
                            "reason": "egress_violation",
                        },
                    )
                )
                await event_bus.publish(str(session_id), {
                    "type": "agent_failed",
                    "agent": agent_type,
                    "execution_id": str(exec_id),
                    "error": result.egress_violation,
                    "reason": "egress_violation",
                    "step": {"order": step.get("order", 0), "status": "failed"},
                }, topic="tasks")
                continue

            if result.safety_violation is not None:
                # WhitelistShim rejected the (slug, args) pair. The shim-block audit
                # row was already persisted inside the helper (kali-scoped); here we
                # finalize the execution row + emit the Tasks-tab failure event.
                await self._db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(
                        status="failed",
                        ended_at=datetime.now(timezone.utc),
                        output_json={"error": result.safety_violation, "reason": "shim_block"},
                    )
                )
                await event_bus.publish(str(session_id), {
                    "type": "agent_failed",
                    "agent": agent_type,
                    "execution_id": str(exec_id),
                    "error": result.safety_violation,
                    "reason": "shim_block",
                    "step": {"order": step.get("order", 0), "status": "failed"},
                }, topic="tasks")
                continue

            if result.error is not None:
                await self._db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(
                        status="failed",
                        ended_at=datetime.now(timezone.utc),
                        output_json={"error": result.error},
                    )
                )
                await event_bus.publish(str(session_id), {
                    "type": "agent_failed",
                    "agent": agent_type,
                    "execution_id": str(exec_id),
                    "error": result.error,
                    "step": {"order": step.get("order", 0), "status": "failed"},
                }, topic="tasks")
                continue

            step_findings = result.findings
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
            # rescope automatically. Runs AFTER row finalization (as in v1.1) so the
            # agent_execution trace is byte-identical. Findings shaped as either:
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
                "step": {"order": step.get("order", 0), "status": "completed"},
            }, topic="tasks")

        return all_findings

    async def _narrate_step(
        self,
        session_id: uuid.UUID,
        step: dict,
        config: dict,
        started_at: datetime,
        result,
    ) -> None:
        """Write a per-step narration MsgChain (role_name = the tool slug) so the
        Agents tab renders a conversational record of each sub-agent on the
        deterministic lane. Best-effort: never raises into the run loop."""
        try:
            agent_type = step.get("agent", "agent")
            action = step.get("action", "")
            target_str = (
                config.get("target")
                or config.get("host")
                or ", ".join(config.get("ip_ranges") or config.get("domains") or [])
                or ""
            )
            description = step.get("description", "")

            if getattr(result, "killed", False):
                status = "failed"
                summary = "Halted — egress monitor tripped (out-of-scope traffic blocked)."
            elif getattr(result, "egress_violation", None):
                status = "failed"
                summary = (
                    f"Halted this step — out-of-scope egress blocked "
                    f"({result.egress_violation}); continuing remaining in-scope steps."
                )
            elif getattr(result, "safety_violation", None):
                status = "failed"
                summary = f"Blocked by safety policy — {result.safety_violation}"
            elif getattr(result, "error", None):
                status = "failed"
                summary = f"Did not complete — {result.error}"
            else:
                findings = result.findings or []
                status = "finished"
                summary = f"Completed — {len(findings)} finding(s)." + _summarize_findings(findings)

            intent = f"{agent_type} · {action}".rstrip(" ·")
            if target_str:
                intent += f"\nTarget: {target_str}"
            if description:
                intent += f"\n{description}"

            now = datetime.now(timezone.utc)
            self._db.add(MsgChain(
                pentest_session_id=session_id,
                role_name=agent_type[:32],
                messages_json=[
                    {"role": "system", "content": intent},
                    {"role": "assistant", "content": summary},
                ],
                started_at=started_at or now,
                ended_at=now,
                status=status,
            ))
            await self._db.flush()
            await event_bus.publish(str(session_id), {
                "type": "msgchain_updated",
                "role": agent_type,
            }, topic="agents")
        except Exception:  # noqa: BLE001 — narration must never break the run
            pass
