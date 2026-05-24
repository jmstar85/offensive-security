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
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import get_role

logger = logging.getLogger(__name__)


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
        from app.safety.exploit_allowlist import filter_plan_steps
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
            "tier": entry.tier.value if hasattr(entry.tier, "value") else str(entry.tier),
        }
        approved, blocked = filter_plan_steps([synthetic_step])
        if blocked:
            return {
                "approved": False,
                "blocked_reason": "exploit_allowlist",
                "blocked_details": blocked,
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

        # Step 5–7: execution + event streaming + audit row are wired in P4
        # where the OrchestratorService bridges Performer with the live
        # PlanExecutor. The P2a dispatcher here returns the validated
        # envelope so unit tests can assert the safety-chain pass.
        result: dict[str, Any] = {
            "approved": True,
            "tool": name,
            "intent": intent,
            "synthetic_step": synthetic_step,
            "same_tool_count": self.state.same_tool_counter[name],
            "total_tool_calls": self.state.total_tool_calls,
            "adviser_should_fire": adviser_fires,
            "adviser_reason": reason,
        }
        return result

    def _concurrency_guard(self) -> "_PerformerLease":
        """Acquire a concurrency slot for this Performer session.

        Returns an async context manager that holds the slot for the duration
        of `run_session`. Raises `PerformerConcurrencyLimit` if the cap is
        reached.
        """
        return _PerformerLease(self.state.session_id)


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


# Hard caps inherited from PentAGI's performer.go (per ADR-003 + v4.0 plan §1).
# Imported by tests; tunable via `settings` for runtime overrides.
PERFORMER_MAX_ITER = settings.performer_max_iter  # default 64
MAX_TOOL_CALLS_GENERAL = settings.pentester_max_tool_calls  # default 100
MAX_TOOL_CALLS_LIMITED = settings.limited_role_max_tool_calls  # default 20
ADVISER_TRIGGER_SAME_TOOL = settings.adviser_trigger_same_tool  # default 5
ADVISER_TRIGGER_TOTAL_TOOL = settings.adviser_trigger_total_tool  # default 10
REFLECTOR_MAX_RETRIES = settings.reflector_max_retries  # default 3
REFLECTOR_BACKOFF_SECONDS = settings.reflector_retry_backoff_seconds  # default [0.2, 1.0, 5.0]
