"""CoordinatorService — deterministic understanding + plan-of-work builder.

Runs after whitelist validation (step 3) but before plan generation (step 5).
No real LLM calls; output is derived deterministically from target+prompt so
tests are reproducible without network access.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.safety.audit import AuditLogger


class UnderstandingOfTarget(BaseModel):
    target_kind: str  # 'web_app'|'network'|'cloud'|'mobile'|'unknown'
    detected_stack: list[str] = []
    entry_points: list[str] = []
    constraints: list[str] = []
    revision_no: int = 0
    raw_signals: dict = {}


class PlanOfWork(BaseModel):
    objectives: list[str]
    family_recommendations: list[dict] = []
    ordered_phases: list[str] = []
    success_criteria: list[str] = []
    revision_no: int = 0


class ReplayLaneViolation(Exception):
    """Raised when CoordinatorService is invoked on a non-eligible lane."""


class UnderstandingBuilder:
    async def build(self, prompt: str, target: dict) -> UnderstandingOfTarget:
        domains: list[str] = target.get("domains", [])
        ip_ranges: list[str] = target.get("ip_ranges", [])

        web_tlds = {".com", ".net", ".org", ".io", ".co", ".edu", ".gov"}
        has_web_domain = any(
            any(d.endswith(tld) for tld in web_tlds) for d in domains
        )
        has_ips = bool(ip_ranges)

        if has_web_domain:
            target_kind = "web_app"
        elif has_ips:
            target_kind = "network"
        else:
            target_kind = "unknown"

        stack_keywords = {
            "apache": "apache",
            "nginx": "nginx",
            "django": "django",
            "flask": "flask",
            "react": "react",
        }
        lower_prompt = prompt.lower()
        detected_stack = [
            label for kw, label in stack_keywords.items() if kw in lower_prompt
        ]

        return UnderstandingOfTarget(
            target_kind=target_kind,
            detected_stack=detected_stack,
            entry_points=domains + ip_ranges,
            raw_signals={"prompt": prompt, "target": target},
        )


class PlanOfWorkBuilder:
    async def build(self, understanding: UnderstandingOfTarget, prompt: str) -> PlanOfWork:
        # Split on commas and periods to derive objectives.
        import re
        parts = re.split(r"[,.]", prompt)
        objectives = [p.strip() for p in parts if p.strip()]
        if not objectives:
            objectives = [prompt.strip()]

        return PlanOfWork(
            objectives=objectives,
            family_recommendations=[
                {"family_kind": "recon", "rationale": "discovery first", "depth_hint": 2}
            ],
            ordered_phases=["recon", "exploit", "extraction"],
            success_criteria=[],
        )


class CoordinatorService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._u = UnderstandingBuilder()
        self._p = PlanOfWorkBuilder()

    async def run(
        self,
        *,
        session_id: uuid.UUID,
        prompt: str,
        target: dict,
        actor_id: str,
        lane: str,
        replay_opt_in: bool = False,
    ) -> tuple[UnderstandingOfTarget, PlanOfWork]:
        if lane == "saved_workflow" and not replay_opt_in:
            raise ReplayLaneViolation(
                "Coordinator must not run on saved-workflow lane without opt-in"
            )

        understanding = await self._u.build(prompt, target)
        plan_of_work = await self._p.build(understanding, prompt)

        # Persist on PentestSession — import lazily to avoid cycles.
        from sqlalchemy import select, update
        from app.models.session import PentestSession

        result = await self._db.execute(
            select(PentestSession).where(PentestSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            revision_no = (session.coordinator_revision_no or 0) + 1
            await self._db.execute(
                update(PentestSession)
                .where(PentestSession.id == session_id)
                .values(
                    understanding_json=understanding.model_dump(),
                    plan_of_work_json=plan_of_work.model_dump(),
                    coordinator_revision_no=revision_no,
                )
            )
        else:
            revision_no = 1

        from app.core.events import event_bus
        await event_bus.publish(
            str(session_id),
            {"type": "understanding_built", "session_id": str(session_id),
             "understanding": understanding.model_dump()},
            topic="coordinator",
        )
        await event_bus.publish(
            str(session_id),
            {"type": "plan_of_work_built", "session_id": str(session_id),
             "plan_of_work": plan_of_work.model_dump()},
            topic="coordinator",
        )

        audit_logger = AuditLogger(self._db)
        await audit_logger.log(
            action="coordinator.run",
            actor_id=actor_id,
            target_entity="pentest_session",
            target_id=str(session_id),
            details={
                "lane": lane,
                "replay_opt_in": replay_opt_in,
                "revision_no": revision_no,
            },
        )

        return (understanding, plan_of_work)

    async def maybe_run_replay_drift_check(
        self,
        *,
        session_id: uuid.UUID,
        saved_plan_json: dict,
        fresh_understanding: UnderstandingOfTarget,
        fresh_plan_of_work: PlanOfWork,
        actor_id: str,
    ) -> bool:
        saved_steps: list[Any] = saved_plan_json.get("steps", [])
        saved_set: set[str] = set()
        for step in saved_steps:
            agent = step.get("agent", "")
            if agent:
                saved_set.update(agent.lower().split("_"))

        fresh_set: set[str] = set()
        for obj in fresh_plan_of_work.objectives:
            fresh_set.update(obj.lower().split())

        union = saved_set | fresh_set
        intersection = saved_set & fresh_set
        jaccard = len(intersection) / len(union) if union else 1.0

        audit_logger = AuditLogger(self._db)

        if jaccard < 0.6:
            await audit_logger.log(
                action="coordinator.replay_drift_detected",
                actor_id=actor_id,
                target_entity="pentest_session",
                target_id=str(session_id),
                details={
                    "jaccard": jaccard,
                    "saved_objective_count": len(saved_steps),
                    "fresh_objective_count": len(fresh_plan_of_work.objectives),
                },
            )
            return True

        return False
