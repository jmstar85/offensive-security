"""Main orchestrator service — full pipeline from prompt to report."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.models.project import Target
from app.models.session import PentestSession
from app.orchestrator.executor import PlanExecutor
from app.orchestrator.planner import AttackPlanner
from app.orchestrator.workflow_plan import (
    WorkflowPlanError,
    normalize_workflow_plan,
    topologically_sorted_steps,
)
from app.reports.generator import ReportGenerator
from app.agents.registry import get_tool_entry
from app.safety.audit import AuditLogger
from app.safety.audit_kali import persist_kali_blocked_steps
from app.safety.exploit_allowlist import filter_by_tier_flags, filter_plan_steps
from app.orchestrator.scope import validate_session_target
from app.safety.risk_filter import RiskFilter

# Claude API rate limiting: max 5 prompts/min per session (simple token bucket)
_rate_buckets: dict[str, tuple[float, int]] = {}


def _check_rate_limit(actor_id: str) -> bool:
    import time
    now = time.monotonic()
    last_time, count = _rate_buckets.get(actor_id, (now, 0))
    if now - last_time > 60:
        _rate_buckets[actor_id] = (now, 1)
        return True
    from app.core.config import settings
    if count >= settings.max_prompts_per_minute:
        return False
    _rate_buckets[actor_id] = (last_time, count + 1)
    return True


class OrchestratorService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._planner = AttackPlanner()
        self._risk_filter = RiskFilter()
        self._audit = AuditLogger(db)

    async def run(
        self, session_id: uuid.UUID, prompt: str, actor_id: uuid.UUID
    ) -> None:
        """Full autonomous pipeline: prompt → plan → safety → execute → report."""

        # 1. Rate limit check
        if not _check_rate_limit(str(actor_id)):
            await self._fail(session_id, "Rate limit exceeded")
            return

        # 2. Load session + target + whitelist
        sess_result = await self._db.execute(
            select(PentestSession).where(PentestSession.id == session_id)
        )
        session = sess_result.scalar_one_or_none()
        if not session:
            return

        target_result = await self._db.execute(
            select(Target).where(Target.project_id == session.project_id)
        )
        target_obj = target_result.scalars().first()
        target = {
            "ip_ranges": target_obj.ip_ranges if target_obj else [],
            "domains": target_obj.domains if target_obj else [],
        }
        whitelist_rules = target_obj.whitelist_rules if target_obj else {}

        # 3. Whitelist validation (Layer 1) — via the SHARED session-start scope
        # gate (PR7 / PM2-B). Pure refactor of the prior inline
        # WhitelistValidator(...).validate_target(...) call; AssistantService.turn
        # runs the SAME callable so both lanes gate the session target identically.
        is_valid, violations = validate_session_target(target, whitelist_rules)
        if not is_valid:
            await self._audit.log(
                action="whitelist_violation",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"violations": violations},
            )
            await self._fail(session_id, f"Whitelist violation: {violations}")
            return

        # 4. Mark session as running
        await self._db.execute(
            update(PentestSession)
            .where(PentestSession.id == session_id)
            .values(status="running", started_at=datetime.now(timezone.utc))
        )
        await self._db.commit()

        # 4.5 Coordinator façade (fresh-plan ONLY, or saved-workflow with explicit opt-in)
        from app.core.config import settings
        from app.orchestrator.coordinator import CoordinatorService, ReplayLaneViolation
        from app.orchestrator.llm.base import ModelUnreachable

        lane = "saved_workflow" if session.plan_json else "fresh_plan"
        # The XBOW autonomous lane (step 9) drives the Performer, which generates
        # and executes its OWN plan from the operator objective. The legacy
        # AttackPlanner pre-pass below is only a hint on that lane, so its failure
        # must not kill an autonomous run (see the plan-generation try/except).
        autonomous_lane = (
            getattr(settings, "osa_xbow_autonomous_enabled", False)
            and lane == "fresh_plan"
        )
        coordinator_replay_enabled = getattr(settings, "osa_coordinator_replay_enabled", False)
        skip_coordinator_replay = bool((session.plan_json or {}).get("skip_coordinator_replay", False))
        replay_opt_in = (lane == "saved_workflow") and coordinator_replay_enabled and not skip_coordinator_replay
        coordinator_enabled = getattr(settings, "osa_coordinator_enabled", False)
        if coordinator_enabled and (lane == "fresh_plan" or replay_opt_in):
            try:
                coordinator = CoordinatorService(self._db)
                understanding, plan_of_work = await coordinator.run(
                    session_id=session_id, prompt=prompt, target=target,
                    actor_id=str(actor_id), lane=lane, replay_opt_in=replay_opt_in,
                )
                await self._db.commit()
                if lane == "saved_workflow" and replay_opt_in:
                    await coordinator.maybe_run_replay_drift_check(
                        session_id=session_id,
                        saved_plan_json=session.plan_json or {},
                        fresh_understanding=understanding,
                        fresh_plan_of_work=plan_of_work,
                        actor_id=str(actor_id),
                    )
                # Materialize per-phase families so the AgentFamilyTree shows
                # the spawned families on the LLM-driven fresh-plan lane too
                # (flag-gated, idempotent).
                if getattr(settings, "osa_xbow_families_enabled", False):
                    await self._materialize_families(
                        session_id, plan_of_work.ordered_phases, actor_id
                    )
            except ReplayLaneViolation:
                await self._audit.log(action="coordinator.skipped_for_replay_lane",
                    actor_id=str(actor_id), target_entity="pentest_session",
                    target_id=str(session_id), details={"lane": lane})
            except ModelUnreachable:
                await self._audit.log(action="coordinator.run_failed_replay_lane",
                    actor_id=str(actor_id), target_entity="pentest_session",
                    target_id=str(session_id), details={"lane": lane})
        elif lane == "saved_workflow":
            await self._audit.log(action="coordinator.skipped_for_replay_lane",
                actor_id=str(actor_id), target_entity="pentest_session",
                target_id=str(session_id), details={"lane": lane, "reason": "no_opt_in"})

        # 4.6 Demo/no-LLM lane: build the deterministic UnderstandingOfTarget +
        # PlanOfWork directly (sidestepping CoordinatorService.run's
        # ReplayLaneViolation guard) so the Coordinator panels populate on a
        # saved-workflow replay, and materialize one root AgentFamilyInstance
        # per ordered phase so the AgentFamilyTree shows the spawned families.
        # Double flag-gated — the default-OFF config and the v1.1
        # byte-identical replay never enter this branch.
        if (
            coordinator_enabled
            and lane == "saved_workflow"
            and getattr(settings, "osa_coordinator_populate_on_replay", False)
        ):
            from app.orchestrator.coordinator import (
                PlanOfWorkBuilder,
                UnderstandingBuilder,
            )

            understanding = await UnderstandingBuilder().build(prompt, target)
            plan_of_work = await PlanOfWorkBuilder().build(understanding, prompt)
            next_revision = (session.coordinator_revision_no or 0) + 1
            await self._db.execute(
                update(PentestSession)
                .where(PentestSession.id == session_id)
                .values(
                    understanding_json=understanding.model_dump(),
                    plan_of_work_json=plan_of_work.model_dump(),
                    coordinator_revision_no=next_revision,
                )
            )
            await self._db.commit()
            await event_bus.publish(str(session_id), {
                "type": "understanding_built",
                "session_id": str(session_id),
                "understanding": understanding.model_dump(),
            }, topic="coordinator")
            await event_bus.publish(str(session_id), {
                "type": "plan_of_work_built",
                "session_id": str(session_id),
                "plan_of_work": plan_of_work.model_dump(),
            }, topic="coordinator")
            await self._audit.log(
                action="coordinator.populated_on_replay",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"revision_no": next_revision},
            )

            # Materialize one root family per ordered phase (flag-gated, idempotent).
            if getattr(settings, "osa_xbow_families_enabled", False):
                await self._materialize_families(
                    session_id, plan_of_work.ordered_phases, actor_id
                )

        if session.plan_json:
            await event_bus.publish(str(session_id), {
                "type": "session_update",
                "status": "running",
                "message": "Executing saved workflow...",
            })
            try:
                plan = normalize_workflow_plan(session.plan_json)
                steps = topologically_sorted_steps(plan)
            except WorkflowPlanError as exc:
                await self._fail(session_id, f"Workflow validation failed: {exc}")
                return
            await self._audit.log(
                action="saved_workflow_execution_started",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"step_count": len(steps)},
            )
            await self._db.execute(
                update(PentestSession)
                .where(PentestSession.id == session_id)
                .values(plan_json=plan)
            )
            await self._db.commit()
        else:
            await event_bus.publish(str(session_id), {
                "type": "session_update",
                "status": "running",
                "message": "Generating attack plan...",
            })

            # 5. Generate plan via Claude API
            await self._audit.log(
                action="plan_generation_started",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"prompt": prompt[:500]},
            )
            try:
                plan = await self._planner.create_plan(prompt, target)
            except Exception as exc:
                # On the autonomous lane the Performer generates + executes its
                # own plan from the objective, so a legacy-planner failure (e.g.
                # no Anthropic credential on an Ollama/Copilot-only deployment)
                # must NOT abort the run — fall back to an empty plan and let the
                # Performer drive. On the non-autonomous PlanExecutor lane the
                # plan IS load-bearing, so there we still fail loudly.
                if autonomous_lane:
                    await self._audit.log(
                        action="plan_generation_skipped_autonomous",
                        actor_id=str(actor_id),
                        target_entity="pentest_session",
                        target_id=str(session_id),
                        details={"error": str(exc)},
                    )
                    plan = {"version": 1, "steps": []}
                else:
                    await self._fail(session_id, f"Plan generation failed: {exc}")
                    return

            # 6. Persist plan
            await self._db.execute(
                update(PentestSession)
                .where(PentestSession.id == session_id)
                .values(plan_json=plan)
            )
            await self._db.commit()
            steps = plan.get("steps", [])

        # Ensure every step carries its ToolEntry tier — the planner does not
        # always emit one, and filter_by_tier_flags reads step["tier"].
        for step in steps:
            if step.get("tier"):
                continue
            entry = get_tool_entry(step.get("agent", ""))
            if entry is not None:
                step["tier"] = entry.tier

        # 7. Exploit allowlist filter (Layer 2)
        approved_steps, plan_blocked = filter_plan_steps(steps)

        # 7b. Tier-gate filter — drops active_recon / active_exploit steps
        # whose required session approval flag is not set. This is the
        # gate that prevents a kali_sqlmap step from running without the
        # operator opting in to active_exploit on the session.
        approved_steps, tier_blocked = filter_by_tier_flags(
            approved_steps, session.approval_flags or {}
        )

        # 7c. Per-step DB-persisted audit rows for kali_* blocks (fix #D).
        # Runs before the summary 'steps_blocked' row so granular per-slug
        # records are queryable in /audit-logs. Non-kali blocks are
        # intentionally only summarised, not exploded.
        await persist_kali_blocked_steps(
            self._audit,
            session_id=session_id,
            actor_id=str(actor_id),
            plan_blocked=plan_blocked,
            tier_blocked=tier_blocked,
        )

        # 8. Risk filter (Layer 3)
        approved_steps, risk_blocked = self._risk_filter.filter_steps(approved_steps)
        blocked_steps = list(plan_blocked) + list(tier_blocked) + list(risk_blocked)

        if blocked_steps:
            await self._audit.log(
                action="steps_blocked",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"blocked": blocked_steps},
            )

        # Make an UNDER-AUTHORIZED run explicit: when steps were dropped only
        # because their tier lacked the required approval flag, the operator would
        # otherwise see a silent "0 findings / completed" (session 09484046). Emit
        # a distinct event with the count + reasons so the UI can say "N steps
        # need active_recon/mid_active/active_exploit approval" instead.
        if tier_blocked:
            await event_bus.publish(str(session_id), {
                "type": "steps_dropped_by_authz",
                "dropped": len(tier_blocked),
                "reasons": sorted({
                    s.get("block_reason", "")
                    for s in tier_blocked
                    if isinstance(s, dict) and s.get("block_reason")
                }),
                "hint": (
                    "Grant the required tier flag on the approval gate "
                    "(or refine the plan) and re-run."
                ),
            }, topic="tasks")

        await event_bus.publish(str(session_id), {
            "type": "session_update",
            "status": "executing",
            "message": f"Executing {len(approved_steps)} steps ({len(blocked_steps)} blocked by safety)",
            "plan": plan,
        })

        # 9. Execute approved steps. The XBOW autonomous lane (flag-gated) drives
        # the Performer engine through the shared runtime safety helper — but ONLY
        # on the fresh-plan lane. Saved-workflow REPLAY always uses the deterministic
        # PlanExecutor (re-runs the exact saved steps) so byte-identical replay holds
        # even when the autonomous flag is ON (PR10 default-flip precondition).
        if autonomous_lane:
            findings = await self._run_autonomous_lane(
                session_id=session_id,
                session=session,
                prompt=prompt,
                steps=approved_steps,
                target=target,
                whitelist_rules=whitelist_rules,
                approval_flags=session.approval_flags or {},
                actor_id=str(actor_id),
            )
        else:
            executor = PlanExecutor(self._db)
            findings = await executor.execute(
                session_id=session_id,
                steps=approved_steps,
                target=target,
                whitelist_rules=whitelist_rules,
                actor_id=str(actor_id),
            )
        await self._db.commit()

        # 10. Generate report
        generator = ReportGenerator(self._db)
        await generator.generate(session_id, findings, plan)
        await self._db.commit()

        # 11. Mark session completed
        await self._db.execute(
            update(PentestSession)
            .where(PentestSession.id == session_id)
            .values(status="completed", ended_at=datetime.now(timezone.utc))
        )
        await self._db.commit()

        await self._audit.log(
            action="session_completed",
            actor_id=str(actor_id),
            target_entity="pentest_session",
            target_id=str(session_id),
            details={"finding_count": len(findings)},
        )
        await self._db.commit()

        await event_bus.publish(str(session_id), {
            "type": "session_update",
            "status": "completed",
            "finding_count": len(findings),
        })

    async def _run_autonomous_lane(
        self,
        *,
        session_id: uuid.UUID,
        session: PentestSession,
        prompt: str,
        steps: list[dict],
        target: dict,
        whitelist_rules: dict,
        approval_flags: dict,
        actor_id: str,
    ) -> list[dict]:
        """XBOW autonomous lane (PR4a): drive the Performer engine behind the flag.

        Binds the session-scoped safety context (one EgressMonitor seeded with the
        session's whitelist_rules + the approval flags for the per-dispatch tier
        gate), registers the Minimal-6 topological roles, and runs the role loop.
        ``_dispatch_tool`` runs the per-dispatch filter trio (incl. tier gate) and
        the shared runtime safety helper for every tool call.

        In PR4a the roles are still fixtures (the live Ollama tool-use loop lands in
        PR4b), so no tools are dispatched yet — this closes the "Performer has no
        live app caller" gap and binds the safety context. Findings accumulate on
        the Performer as roles begin dispatching (PR4b+).
        """
        from app.orchestrator.performer import Performer, PerformerConcurrencyLimit

        performer = Performer(self._db, session_id)
        performer.bind_live_execution(
            target=target,
            approval_flags=approval_flags,
            whitelist_rules=whitelist_rules,
            actor_id=actor_id,
        )
        # Seed the operator objective + the approved plan so the Pentester tool-use
        # loop knows WHAT to do (without the objective the LLM has no task).
        performer.state.context["objective"] = prompt
        performer.state.context["approved_steps"] = list(steps)

        # PR6 (A1b / Blocking 2): store ONLY the session-constant inputs used to
        # build the per-role client_factory — never a minted client. run_session
        # and delegate_tool_call build the factory from these on every invocation,
        # so a mid-session credential revoke is honored on the next role call and
        # last_used_at/audit is written on every resolve (no session-lived cache).
        performer.state.context["role_client_inputs"] = {
            "db": self._db,
            "session": session,
            "actor_id": actor_id,
        }

        # Understanding-driven dispatch (PR6 / C3): derive the AttackVector from the
        # session's Understanding to PRIORITIZE the executor's palette. The Pentester
        # gets the vector palette UNION a core recon set, so recon is always possible
        # even when the target_kind heuristic misclassifies (e.g. scanme.nmap.org →
        # web_app by TLD); the vector still steers via context["attack_vector"] + the
        # objective prompt. Understanding-INFORMED, not understanding-RESTRICTED.
        from app.orchestrator.roles.seed_xbow import coerce_vector, vector_to_tool_palette

        understanding = await self._load_understanding(session_id)
        vector = coerce_vector(understanding.get("target_kind") if understanding else None)
        palette = list(vector_to_tool_palette.get(vector, []))
        performer.state.context["attack_vector"] = vector.value

        _RECON_BASE = {"nmap", "httpx", "passive_recon", "subfinder", "dnsx"}
        from app.orchestrator.roles.pentester import Pentester

        performer.register_role(Pentester(
            tools_allowed=sorted(set(palette) | _RECON_BASE | {"ask", "done", "search_in_memory"})
        ))
        # Register the remaining topological roles; run_session skips unregistered.
        # Import the role-seed module first so generator + reporter are present in
        # ROLE_REGISTRY — their modules are otherwise imported by no production
        # code, so without this the register_role_by_name calls below KeyError and
        # get silently skipped, leaving a run with only a pentester chain and no
        # report role. Seed populates the catalog (module-level register_role
        # decorators); the loop still only registers generator + reporter on this
        # performer instance.
        from app.orchestrator.roles import seed  # noqa: F401
        for role_name in ("generator", "reporter"):
            try:
                performer.register_role_by_name(role_name)
            except Exception:  # noqa: BLE001 — role not in registry → skip
                continue
        try:
            await performer.run_session()
        except PerformerConcurrencyLimit as exc:
            await self._audit.log(
                action="performer.concurrency_limit",
                actor_id=actor_id,
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"error": str(exc)},
            )
        return list(performer.state.findings)

    async def _load_understanding(self, session_id: uuid.UUID) -> dict | None:
        """Read the session's persisted Understanding-of-Target (PR6 dispatch input)."""
        row = (
            await self._db.execute(
                select(PentestSession.understanding_json).where(
                    PentestSession.id == session_id
                )
            )
        ).scalar_one_or_none()
        return row if isinstance(row, dict) else None

    async def _materialize_families(
        self, session_id: uuid.UUID, ordered_phases: list[str], actor_id: uuid.UUID
    ) -> None:
        """Insert one root AgentFamilyInstance per ordered phase.

        Idempotent: no-ops when rows already exist for the session (re-run
        safety). Drives the AgentFamilyTree panel.
        """
        from app.models.agent_family import AgentFamilyInstance

        existing = await self._db.execute(
            select(AgentFamilyInstance.id).where(
                AgentFamilyInstance.pentest_session_id == session_id
            )
        )
        if existing.first() is not None:
            return
        for phase in ordered_phases:
            self._db.add(AgentFamilyInstance(
                pentest_session_id=session_id,
                family_kind=phase,
                parent_family_id=None,
                status="active",
                depth=0,
                max_depth=3,
                context_json={"phase": phase},
            ))
        await self._db.commit()
        await self._audit.log(
            action="coordinator.families_materialized",
            actor_id=str(actor_id),
            target_entity="pentest_session",
            target_id=str(session_id),
            details={"families": list(ordered_phases)},
        )

    async def _fail(self, session_id: uuid.UUID, reason: str) -> None:
        await self._db.execute(
            update(PentestSession)
            .where(PentestSession.id == session_id)
            .values(status="failed", ended_at=datetime.now(timezone.utc))
        )
        await self._db.commit()
        await event_bus.publish(str(session_id), {
            "type": "session_update",
            "status": "failed",
            "message": reason,
        })
