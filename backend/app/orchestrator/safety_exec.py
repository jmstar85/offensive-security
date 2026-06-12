"""Shared runtime safety-execution helper (PR2 / C7 core).

``execute_tool_through_safety_chain`` owns the INNER per-adapter-call envelope and
RETURNS a structured result. It is the ONE sanctioned call site for
``<adapter>.execute(...)`` (enforced by
``tests/ast/test_adapter_execute_only_via_safety_helper.py``), so every code path
that runs a tool container — the deterministic ``PlanExecutor`` lane today, the
autonomous ``Performer._dispatch_tool`` lane in PR4a — inherits the identical live
runtime brakes instead of re-implementing (and under-implementing) them.

Boundary (the PR2 BLOCKING decision, implemented):

  INSIDE this helper:
    - ``get_adapter(slug).execute(...)`` through shims / IMAGE_REGEX
    - the ``async for`` over its event stream
    - per-log ``EgressMonitor.monitor_log_line`` (egress brake) → signals ``killed``
    - the container id, surfaced to the caller via ``on_container_id`` so the caller
      writes it onto its ``AgentExecution`` row — the kill switch finds live
      containers by reading ``AgentExecution.container_id`` (kill_switch.py:37), so
      registration must happen mid-run, in the caller's row
    - per-event forwarding via ``on_event`` so the caller publishes to its topics
    - ``SafetyViolation`` → ``persist_kali_shim_block`` (kali-scoped shim-audit brake)

  STAYS in each caller (deliberately NOT here, to keep the deterministic lane
  byte-identical):
    - ``AgentExecution`` row creation + status/output_json finalization
    - the ``tasks``/``terminal``/``agents`` topic publishes (the caller's ``on_event``
      closure performs them with its own ``execution_id``)
    - the plan-time filter trio (``filter_plan_steps`` / ``filter_by_tier_flags`` /
      ``RiskFilter``) — that runs at plan cardinality per lane, not per adapter call
    - the rescope harvest + ``RescopeService.pause_for_rescope`` — in the current
      executor that runs AFTER the row is finalized to ``completed`` (executor.py:153
      then :167), so it stays in the caller to preserve that ordering and the
      byte-identical agent_execution trace

Returning results (rather than driving the row lifecycle) is what keeps the
deterministic lane byte-identical: ``PlanExecutor`` still creates AND finalizes its
``AgentExecution`` rows in its own loop, so no row-creation/finalization site moves.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.kali_whitelist import SafetyViolation
from app.agents.registry import get_adapter
from app.safety.audit import AuditLogger
from app.safety.audit_kali import persist_kali_shim_block
from app.safety.egress_monitor import EgressMonitor


@dataclass
class SafetyExecResult:
    """Outcome of running one tool step through the runtime brake envelope.

    Exactly one of {success (``error``/``safety_violation``/``killed`` all falsy),
    ``safety_violation``, ``error``, ``killed``} describes the terminal state. The
    caller maps it onto its ``AgentExecution`` row + topic publishes.
    """

    findings: list[dict] = field(default_factory=list)
    container_id: str | None = None
    killed: bool = False                  # egress monitor tripped → session killed
    safety_violation: str | None = None   # WhitelistShim rejection → row reason=shim_block
    error: str | None = None              # generic adapter failure → row failed


async def execute_tool_through_safety_chain(
    step: dict,
    target: dict,
    *,
    egress_monitor: EgressMonitor,
    audit: AuditLogger,
    session_id: Any,
    actor_id: str,
    on_event: Callable[[Any], Awaitable[None]] | None = None,
    on_container_id: Callable[[str], Awaitable[None]] | None = None,
) -> SafetyExecResult:
    """Run one tool ``step`` through the adapter and the live runtime brakes.

    ``egress_monitor`` is constructed once per session by the caller (seeded with
    the session's ``whitelist_rules``) and threaded into every call. ``on_event`` and
    ``on_container_id`` are caller-owned async sinks (topic publish + row write) so
    this helper never touches the ``AgentExecution`` lifecycle or the event bus
    directly.
    """
    agent_type = step["agent"]
    config = step.get("config", {})
    result = SafetyExecResult()

    adapter = get_adapter(agent_type)
    container_id_holder: list[str] = []
    seen_container_id = False
    step_findings: list[dict] = []

    try:
        async for event in adapter.execute(target, config, container_id_holder):
            # Register container id (once) so the kill switch can find a live
            # container mid-run; the caller writes it onto the AgentExecution row.
            if container_id_holder and not seen_container_id:
                seen_container_id = True
                result.container_id = container_id_holder[0]
                if on_container_id is not None:
                    await on_container_id(container_id_holder[0])

            # Egress brake on log lines.
            if event.event_type == "log":
                line = event.data.get("line", "")
                safe = await egress_monitor.monitor_log_line(line, actor_id)
                if not safe:
                    result.killed = True
                    return result

            if on_event is not None:
                await on_event(event)

            if event.event_type == "status" and "result" in event.data:
                step_findings = event.data["result"].get("findings", [])

    except SafetyViolation as exc:
        # WhitelistShim rejected the (slug, args) pair at build_command time.
        # Persist the per-step shim-block audit row (kali-scoped) so operators see
        # it in /audit-logs; the row finalization to status=failed stays in the caller.
        if agent_type.startswith("kali_"):
            await persist_kali_shim_block(
                audit,
                session_id=session_id,
                actor_id=actor_id,
                agent=agent_type,
                tool_slug=config.get("tool_slug"),
                reason=str(exc),
            )
        result.safety_violation = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 — mirrors the executor's catch-all
        result.error = str(exc)
        return result

    result.findings = step_findings
    return result
