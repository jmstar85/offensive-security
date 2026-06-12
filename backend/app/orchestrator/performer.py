"""Performer engine (v4.0 P1 skeleton) — PentAGI port of `pentagi/backend/pkg/providers/performer.go`.

P1 ships the skeleton only:
- Class structure + lifecycle hooks
- Role registry integration
- Concurrency cap (ADR-003: single coroutine per session)
- Iteration cap (`PERFORMER_MAX_ITER`)
- `_dispatch_tool` stub (raises NotImplementedError; wired in P2a)

P2a fills in:
- `_dispatch_tool` — resolves `AgentAdapter` via `get_adapter()` (ADR-005)
- Adviser auto-injection on `EXECUTION_MONITOR` thresholds
- Reflector wrap with retries + exponential backoff

P4 wires Performer into `OrchestratorService.run` behind `osa_flow_ui_enabled`.

Concurrency invariant (ADR-003): each Performer instance corresponds to exactly
one `PentestSession.id`. The engine runs roles in cooperative-coroutine order;
no `asyncio.Task` fan-out per role. Multiple sessions on the single uvicorn
worker share the event loop but are capped at `settings.max_concurrent_performer_sessions`.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.orchestrator.llm.context import CURRENT_USER_ID  # noqa: F401 — re-exported for tests
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import get_role

logger = logging.getLogger(__name__)


def _spawn_with_context(coro: Any) -> "asyncio.Task[Any]":
    """Schedule *coro* as a Task that inherits a snapshot of the current context.

    copy_context() captures the current ContextVar state at call time so that
    CURRENT_USER_ID (and any other ContextVars) are visible inside the task
    even after the parent context mutates them.
    """
    ctx = copy_context()
    return asyncio.get_event_loop().create_task(coro, context=ctx)


# Track active Performer instances per session for the concurrency cap.
# Module-level so the cap survives across requests within one uvicorn worker.
_active_performers: set[UUID] = set()
_active_lock = asyncio.Lock()


class PerformerConcurrencyLimit(Exception):
    """Raised when starting a new Performer would exceed `settings.max_concurrent_performer_sessions`."""


# Topological order for the Minimal 6 v1 role chain. Generator drafts the
# plan + ambiguity, Pentester executes against the v3.2.1 adapter registry,
# Reporter wraps up. Memorist / Adviser / Reflector are auxiliary roles
# invoked by the linear chain via tool calls / wrappers — NOT in the order.
ROLE_TOPOLOGICAL_ORDER: list[str] = ["generator", "pentester", "reporter"]


@dataclass
class PerformerSession:
    """Per-session Performer state. One instance per `PentestSession.id`."""

    db: AsyncSession
    session_id: UUID
    roles: dict[str, Role] = field(default_factory=dict)
    iteration: int = 0
    same_tool_counter: dict[str, int] = field(default_factory=dict)
    total_tool_calls: int = 0
    # Shared context dict passed into every Role.run() so roles can read
    # prior turn output (e.g. Generator's draft_plan feeds Pentester).
    context: dict[str, Any] = field(default_factory=dict)
    # PR4a: live autonomous-lane execution context. ``egress_monitor`` is None on
    # the P2a envelope-only path (unit tests that assert the safety-chain pass
    # without executing); it is set by ``Performer.bind_live_execution()`` on the
    # XBOW lane, and its presence switches ``_dispatch_tool`` from envelope-only to
    # live execution through the shared runtime safety helper.
    target: dict[str, Any] | None = None
    approval_flags: dict[str, bool] = field(default_factory=dict)
    whitelist_rules: dict[str, Any] = field(default_factory=dict)
    actor_id: str | None = None
    egress_monitor: Any | None = None
    findings: list[dict] = field(default_factory=list)


class Performer:
    """Cooperative-coroutine role runner per session.

    P1 skeleton: structure + concurrency cap + iteration cap. P2a populates
    `_dispatch_tool` with the structured tool-call envelope (ADR-005) that
    routes to existing `AgentAdapter`s via `get_adapter()` and the v3.2.1
    safety chain.
    """

    def __init__(self, db: AsyncSession, session_id: UUID) -> None:
        self.state = PerformerSession(db=db, session_id=session_id)

    def register_role(self, role: Role) -> None:
        """Bind a Role instance to this Performer session."""
        self.state.roles[role.name] = role

    def register_role_by_name(self, name: str, **kwargs: Any) -> None:
        """Look up a Role class in ROLE_REGISTRY and instantiate it."""
        role_cls = get_role(name)
        self.state.roles[name] = role_cls(**kwargs)

    def bind_live_execution(
        self,
        *,
        target: dict[str, Any],
        approval_flags: dict[str, bool] | None,
        whitelist_rules: dict[str, Any] | None,
        actor_id: str,
    ) -> None:
        """Bind the live autonomous-lane execution context (PR4a).

        Constructs ONE session-scoped ``EgressMonitor`` seeded with the session's
        ``whitelist_rules`` (the SAME source the deterministic ``PlanExecutor`` uses
        — ``OrchestratorService.run`` reads ``Target.whitelist_rules``) and threads
        it into every ``_dispatch_tool`` call. Its presence is what switches
        ``_dispatch_tool`` from envelope-only validation to live execution through
        ``execute_tool_through_safety_chain``.
        """
        from app.safety.egress_monitor import EgressMonitor

        self.state.target = target
        self.state.approval_flags = approval_flags or {}
        self.state.whitelist_rules = whitelist_rules or {}
        self.state.actor_id = actor_id
        self.state.egress_monitor = EgressMonitor(
            self.state.session_id, self.state.whitelist_rules
        )

    async def run_session(self) -> list[RoleResult]:
        """Drive the role loop for this session up to `PERFORMER_MAX_ITER`.

        Iterates registered roles in topological order
        (Generator → Pentester → Reporter) and wraps each `Role.run()` in the
        Reflector retry policy. Auxiliary roles (Memorist / Adviser /
        Reflector itself) are invoked by the linear chain on demand via tool
        calls and wrappers — they do NOT participate in this loop.

        Halt conditions:
        - A role returns `error` (Reflector-wrapped) → halt + propagate up
        - Reporter returns `finished=True` → normal completion
        - `iteration` exceeds `PERFORMER_MAX_ITER` → halt with warning

        Roles missing from the registered set are skipped (e.g. test fixtures
        that only register Generator + Reporter).
        """
        from app.orchestrator.roles.reflector import wrap as reflector_wrap

        async with self._concurrency_guard():
            if not self.state.roles:
                logger.info(
                    "Performer.run_session called with no roles; "
                    "nothing to drive. Returning empty result."
                )
                return []

            results: list[RoleResult] = []
            for role_name in ROLE_TOPOLOGICAL_ORDER:
                role = self.state.roles.get(role_name)
                if role is None:
                    # Session opted out of this role — common in v4.0
                    # AmbiguityLoop, which only uses Generator.
                    continue

                self.state.iteration += 1
                if self.state.iteration > PERFORMER_MAX_ITER:
                    logger.warning(
                        "PERFORMER_MAX_ITER (%d) reached at role=%s; halting loop.",
                        PERFORMER_MAX_ITER,
                        role_name,
                    )
                    break

                result = await reflector_wrap(
                    role.run, performer=self, context=self.state.context
                )
                await self._publish_role_turn(role_name, result)
                results.append(result)

                if result.error:
                    logger.error(
                        "Role %s failed after retries: %s. Halting loop.",
                        role_name,
                        result.error,
                    )
                    break

                # Pipe each role's primary output into the shared context so
                # downstream roles can read it. Generator's last assistant
                # message becomes Pentester's input; Pentester's output feeds
                # Reporter.
                if result.messages:
                    self.state.context[f"{role_name}_output"] = result.messages[-1].get(
                        "content"
                    )

                if role_name == "reporter" and result.finished:
                    break

            return results

    async def _publish_role_turn(self, role_name: str, role_result: RoleResult) -> None:
        """Publish a role turn to topic='conversation' (scrubbed) and topic='raw_conversation' (unscrubbed).
        Both topics are rate-limited 50 events/sec/session per SF-CRITIC-9."""
        from app.core.events import event_bus
        from app.observability.metrics import conversation_topic_dropped_events_total
        from app.safety.conversation_scrubber import ConversationScrubber
        last_msg = role_result.messages[-1] if role_result.messages else {}
        raw_text = str(last_msg.get("content", ""))
        scrubber = ConversationScrubber(session_id=self.state.session_id)
        result = scrubber.scrub(raw_text)
        if not self._consume_publish_token():
            conversation_topic_dropped_events_total.inc(
                1.0,
                session_id=str(self.state.session_id),
                topic="conversation",
            )
            conversation_topic_dropped_events_total.inc(
                1.0,
                session_id=str(self.state.session_id),
                topic="raw_conversation",
            )
            return
        await event_bus.publish(str(self.state.session_id), {
            "type": "role_turn",
            "role": role_name,
            "iteration": self.state.iteration,
            "content": result.scrubbed_text,
            "layer_hits": result.layer_hits,
            "circuit_open": result.circuit_open,
        }, topic="conversation")
        await event_bus.publish(str(self.state.session_id), {
            "type": "role_turn_raw",
            "role": role_name,
            "iteration": self.state.iteration,
            "content": raw_text,
        }, topic="raw_conversation")

    def _consume_publish_token(self) -> bool:
        """Token-bucket: 50 capacity, refill 50/sec. Oldest-dropped on overflow."""
        import time
        now = time.monotonic()
        state = self.state.context.setdefault("_publish_bucket", {"tokens": 50.0, "last": now})
        elapsed = now - state["last"]
        state["tokens"] = min(50.0, state["tokens"] + elapsed * 50.0)
        state["last"] = now
        if state["tokens"] < 1.0:
            return False
        state["tokens"] -= 1.0
        return True

    async def _dispatch_tool(
        self,
        name: str,
        payload: dict[str, Any],
        target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Structured tool dispatch (ADR-005 envelope).

        Wired in P2a:
        1. Validate `name` ∈ `list_agent_types()`.
        2. Validate `payload["intent"]` ∈ `INTENT_VOCABULARY` (closed enum).
        3. Resolve adapter via `get_adapter(name)`.
        4. Run safety chain (exploit_allowlist + risk_filter) on the synthetic
           single-step plan derived from the tool call.
        5. If approved, invoke `adapter.execute(target, payload["config"])`
           and aggregate events.
        6. Persist `AgentExecution` row.
        7. Emit `event_bus.publish(session_id, ..., topic="session")` per event.
        8. Track per-tool counters for Adviser auto-injection.

        Returns a dict with `{approved, blocked_reason?, events?, execution_id?}`
        so the caller (the role's chain) can update its own message stream.
        Whitelist validation happens at session start (OrchestratorService.run
        already runs it before any Performer dispatch) so this dispatcher
        does not re-check the target scope; if v3.4 enables rescope mid-flow
        without going through OrchestratorService, this contract must add a
        whitelist re-check.
        """
        # Lazy imports break a circular dep cycle: performer.py is imported
        # by service.py, which itself imports the safety layers.
        from app.agents.registry import get_tool_entry, list_agent_types
        from app.agents.intent_vocabulary import INTENT_VOCABULARY
        from app.orchestrator.roles.adviser import should_trigger
        from app.safety.exploit_allowlist import filter_by_tier_flags, filter_plan_steps
        from app.safety.risk_filter import RiskFilter

        intent = payload.get("intent")
        config = payload.get("config", {})

        # Step 1+2: validate envelope.
        if name not in list_agent_types():
            return {
                "approved": False,
                "blocked_reason": f"unknown_tool_slug:{name}",
            }
        if intent and intent not in INTENT_VOCABULARY:
            return {
                "approved": False,
                "blocked_reason": f"unknown_intent_slug:{intent}",
            }

        # Step 3: resolve the registry entry (no adapter instantiation yet —
        # the actual `adapter.execute(target, config)` invocation is wired in
        # P4 alongside the live execution context). We use the entry's tier
        # for the safety filters here.
        entry = get_tool_entry(name)
        if entry is None:
            return {"approved": False, "blocked_reason": f"unknown_tool_slug:{name}"}

        # Step 4: safety chain — synthesize one step for the filters.
        synthetic_step = {
            "order": self.state.total_tool_calls + 1,
            "agent": name,
            "action": intent or "execute",
            "description": payload.get("description", ""),
            "config": config,
            "tier": entry.tier.value if hasattr(entry.tier, "value") else str(entry.tier),  # type: ignore[union-attr]
        }
        approved, blocked = filter_plan_steps([synthetic_step])
        if blocked:
            return {
                "approved": False,
                "blocked_reason": "exploit_allowlist",
                "blocked_details": blocked,
            }

        # Step 4b (PR4a): per-dispatch tier gate — the autonomous-lane equivalent
        # of the deterministic lane's service.py:274 gate. ONLY on the bound live
        # lane; the unbound P2a envelope-only path preserves legacy behavior
        # (skeleton tests assert the validated envelope without supplying flags).
        bound = self.state.egress_monitor is not None
        if bound:
            approved, tier_blocked = filter_by_tier_flags(
                approved, self.state.approval_flags or {}
            )
            if tier_blocked:
                return {
                    "approved": False,
                    "blocked_reason": "tier_gate",
                    "blocked_details": tier_blocked,
                }

        risk_filter = RiskFilter()
        approved, risk_blocked = risk_filter.filter_steps(approved)
        if not approved:
            return {
                "approved": False,
                "blocked_reason": "risk_filter",
                "blocked_details": risk_blocked,
            }

        # Update counters for Adviser before invoking the adapter (so Adviser
        # can fire on the FIRST excessive call, not after the fact).
        self.state.same_tool_counter[name] = self.state.same_tool_counter.get(name, 0) + 1
        self.state.total_tool_calls += 1
        adviser_fires, reason = should_trigger(
            same_tool_max=self.state.same_tool_counter[name],
            total_tool_calls=self.state.total_tool_calls,
        )

        # Validated envelope (the P2a contract — preserved keys).
        envelope: dict[str, Any] = {
            "approved": True,
            "tool": name,
            "intent": intent,
            "synthetic_step": synthetic_step,
            "same_tool_count": self.state.same_tool_counter[name],
            "total_tool_calls": self.state.total_tool_calls,
            "adviser_should_fire": adviser_fires,
            "adviser_reason": reason,
        }

        # Step 5–7 (PR4a): on the bound live lane, execute through the shared
        # runtime safety helper with this Performer's OWN AgentExecution lifecycle.
        # The unbound P2a path returns the validated envelope only (no execution).
        if not bound:
            return envelope

        exec_outcome = await self._execute_step_through_helper(synthetic_step)
        envelope.update(exec_outcome)
        return envelope

    async def _execute_step_through_helper(
        self, step: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one validated step through the shared runtime safety helper, with
        this Performer's OWN ``AgentExecution`` row lifecycle + topic publishes (PR4a).

        Mirrors ``PlanExecutor``'s per-step body but owns its own rows so the
        autonomous lane inherits the full runtime brake envelope (egress monitor,
        container-id kill registration, rescope pause, shim-block audit) via
        ``execute_tool_through_safety_chain`` — the SAME single sanctioned
        adapter-execute site the deterministic lane uses. The rescope harvest runs
        AFTER row finalization, matching the deterministic ordering.
        """
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.core.events import event_bus
        from app.models.session import AgentExecution
        from app.orchestrator.rescope_service import DiscoveredTarget, RescopeService
        from app.orchestrator.safety_exec import execute_tool_through_safety_chain
        from app.safety.audit import AuditLogger

        db = self.state.db
        session_id = self.state.session_id
        actor_id = self.state.actor_id or ""
        agent_type = step["agent"]
        config = step.get("config", {})
        audit = AuditLogger(db)
        # Invariant: only reached on the bound live lane (egress_monitor set).
        egress_monitor = self.state.egress_monitor
        assert egress_monitor is not None

        execution = AgentExecution(
            session_id=session_id,
            agent_type=agent_type,
            status="running",
            config_json=config,
            started_at=datetime.now(timezone.utc),
        )
        db.add(execution)
        await db.flush()
        exec_id = execution.id

        await event_bus.publish(str(session_id), {
            "type": "agent_started",
            "agent": agent_type,
            "execution_id": str(exec_id),
            "step": step.get("order", 0),
        }, topic="tasks")

        async def _register_container(container_id: str) -> None:
            if not execution.container_id:
                execution.container_id = container_id
                await db.execute(
                    update(AgentExecution)
                    .where(AgentExecution.id == exec_id)
                    .values(container_id=container_id)
                )

        async def _publish_event(event) -> None:
            topic = "terminal" if event.event_type == "log" else "agents"
            await event_bus.publish(str(session_id), {
                "type": event.event_type,
                "agent": event.agent_type,
                "execution_id": str(exec_id),
                "data": event.data,
            }, topic=topic)

        result = await execute_tool_through_safety_chain(
            step,
            self.state.target or {},
            egress_monitor=egress_monitor,
            audit=audit,
            session_id=session_id,
            actor_id=actor_id,
            on_event=_publish_event,
            on_container_id=_register_container,
        )

        if result.killed:
            return {"executed": True, "killed": True,
                    "execution_id": str(exec_id), "findings": []}

        if result.safety_violation is not None:
            await db.execute(
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
            }, topic="tasks")
            return {"executed": True, "safety_violation": result.safety_violation,
                    "execution_id": str(exec_id), "findings": []}

        if result.error is not None:
            await db.execute(
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
            }, topic="tasks")
            return {"executed": True, "error": result.error,
                    "execution_id": str(exec_id), "findings": []}

        step_findings = result.findings
        self.state.findings.extend(step_findings)
        await db.execute(
            update(AgentExecution)
            .where(AgentExecution.id == exec_id)
            .values(
                status="completed",
                ended_at=datetime.now(timezone.utc),
                output_json={"findings": step_findings},
            )
        )

        # Rescope harvest (after row finalize — same ordering as PlanExecutor).
        new_host_records: list[DiscoveredTarget] = []
        for f in step_findings:
            if not isinstance(f, dict):
                continue
            for nh in (f.get("new_hosts") or []):
                host = nh.get("host") if isinstance(nh, dict) else None
                tier = (nh.get("tier") if isinstance(nh, dict) else None) or "passive_recon"
                if host:
                    new_host_records.append(DiscoveredTarget(
                        host=host, tier=tier,
                        discovered_by_step_id=str(step.get("order", "")),
                    ))
            if f.get("is_new") and f.get("host"):
                new_host_records.append(DiscoveredTarget(
                    host=f["host"], tier=f.get("tier", "passive_recon"),
                    discovered_by_step_id=str(step.get("order", "")),
                ))

        paused = False
        rescope_id: str | None = None
        if new_host_records:
            rescope = RescopeService(db)
            try:
                approval = await rescope.pause_for_rescope(
                    session_id=session_id,
                    discovered=new_host_records,
                    requesting_step_id=str(step.get("order", "")),
                )
                if approval is not None:
                    paused = True
                    rescope_id = str(approval.id)
                    await event_bus.publish(str(session_id), {
                        "type": "session_update",
                        "status": "paused_for_rescope",
                        "rescope_id": rescope_id,
                    }, topic="session")
            except Exception as exc:  # noqa: BLE001
                await audit.log(
                    action="rescope_trigger_failed",
                    actor_id=actor_id,
                    target_entity="pentest_session",
                    target_id=str(session_id),
                    details={"error": str(exc)},
                )

        if not paused:
            await event_bus.publish(str(session_id), {
                "type": "agent_completed",
                "agent": agent_type,
                "execution_id": str(exec_id),
                "finding_count": len(step_findings),
            }, topic="tasks")

        return {"executed": True, "findings": step_findings,
                "execution_id": str(exec_id),
                "paused_for_rescope": paused, "rescope_id": rescope_id}

    def _concurrency_guard(self) -> "_PerformerLease":
        """Acquire a concurrency slot for this Performer session.

        Returns an async context manager that holds the slot for the duration
        of `run_session`. Raises `PerformerConcurrencyLimit` if the cap is
        reached.
        """
        return _PerformerLease(self.state.session_id)

    def _family_concurrency_guard(self, family_kind: str, max_concurrent: int = 4) -> "_FamilyLease":
        """Acquire a per-family sub-lease. MUST be used inside the per-session lease."""
        return _FamilyLease(self.state.session_id, family_kind, max_concurrent)


class _PerformerLease:
    """Async context manager for the per-session concurrency lease.

    Implements the ADR-003 cap by serializing entry through `_active_lock`
    and rejecting when `len(_active_performers) >= max_concurrent`.
    """

    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id

    async def __aenter__(self) -> "_PerformerLease":
        async with _active_lock:
            if len(_active_performers) >= settings.max_concurrent_performer_sessions:
                raise PerformerConcurrencyLimit(
                    f"Performer concurrency cap reached "
                    f"({settings.max_concurrent_performer_sessions}); "
                    f"active sessions: {sorted(str(s) for s in _active_performers)}"
                )
            _active_performers.add(self.session_id)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        async with _active_lock:
            _active_performers.discard(self.session_id)


# Per-session per-family active count. Key = (session_id, family_kind). Outer
# bound is _active_performers (per-session); this inner bound caps individual
# family fan-out per SF-CRITIC-6.
_family_active_counts: dict[tuple[UUID, str], int] = {}


class FamilyConcurrencyLimit(Exception):
    """Raised when starting a new family member would exceed the family sub-cap."""


class _FamilyLease:
    """Async context manager for a per-family concurrency lease.

    Per SF-CRITIC-6: max_concurrent_per_family default 4, hard ceiling 8.
    Sits INSIDE the per-session _PerformerLease — caller must already
    hold a session lease.
    """

    def __init__(self, session_id: UUID, family_kind: str, max_concurrent: int = 4) -> None:
        from app.orchestrator.roles.seed_xbow import FamilySpawner
        if max_concurrent > FamilySpawner.MAX_CONCURRENT_PER_FAMILY_HARD_CEILING:
            raise ValueError(
                f"max_concurrent={max_concurrent} exceeds hard ceiling "
                f"{FamilySpawner.MAX_CONCURRENT_PER_FAMILY_HARD_CEILING} (SF-CRITIC-6)"
            )
        self.session_id = session_id
        self.family_kind = family_kind
        self.max_concurrent = max_concurrent

    async def __aenter__(self) -> "_FamilyLease":
        async with _active_lock:
            key = (self.session_id, self.family_kind)
            count = _family_active_counts.get(key, 0)
            if count >= self.max_concurrent:
                raise FamilyConcurrencyLimit(
                    f"Family '{self.family_kind}' concurrency cap reached "
                    f"({self.max_concurrent}) for session {self.session_id}"
                )
            _family_active_counts[key] = count + 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        async with _active_lock:
            key = (self.session_id, self.family_kind)
            if _family_active_counts.get(key, 0) > 0:
                _family_active_counts[key] -= 1
            if _family_active_counts.get(key, 0) == 0:
                _family_active_counts.pop(key, None)


# Hard caps inherited from PentAGI's performer.go (per ADR-003 + v4.0 plan §1).
# Imported by tests; tunable via `settings` for runtime overrides.
PERFORMER_MAX_ITER = settings.performer_max_iter  # default 64
MAX_TOOL_CALLS_GENERAL = settings.pentester_max_tool_calls  # default 100
MAX_TOOL_CALLS_LIMITED = settings.limited_role_max_tool_calls  # default 20
ADVISER_TRIGGER_SAME_TOOL = settings.adviser_trigger_same_tool  # default 5
ADVISER_TRIGGER_TOTAL_TOOL = settings.adviser_trigger_total_tool  # default 10
REFLECTOR_MAX_RETRIES = settings.reflector_max_retries  # default 3
REFLECTOR_BACKOFF_SECONDS = settings.reflector_retry_backoff_seconds  # default [0.2, 1.0, 5.0]
