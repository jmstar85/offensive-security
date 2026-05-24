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
from app.safety.audit import AuditLogger
from app.safety.exploit_allowlist import filter_plan_steps
from app.safety.risk_filter import RiskFilter
from app.safety.whitelist import WhitelistValidator

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

        # 3. Whitelist validation (Layer 1)
        validator = WhitelistValidator(whitelist_rules)
        is_valid, violations = validator.validate_target(target)
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

        # 7. Exploit allowlist filter (Layer 2)
        approved_steps, blocked_steps = filter_plan_steps(steps)

        # 8. Risk filter (Layer 3)
        approved_steps, risk_blocked = self._risk_filter.filter_steps(approved_steps)
        blocked_steps.extend(risk_blocked)

        if blocked_steps:
            await self._audit.log(
                action="steps_blocked",
                actor_id=str(actor_id),
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"blocked": blocked_steps},
            )

        await event_bus.publish(str(session_id), {
            "type": "session_update",
            "status": "executing",
            "message": f"Executing {len(approved_steps)} steps ({len(blocked_steps)} blocked by safety)",
            "plan": plan,
        })

        # 9. Execute approved steps
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
