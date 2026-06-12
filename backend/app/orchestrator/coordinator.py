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


class IterationCapHit(Exception):
    """Raised by run_with_iteration_cap when one of the caps trips."""

    def __init__(self, reason: str, *, iterations: int, wall_clock_s: float, tokens: int):
        super().__init__(reason)
        self.reason = reason
        self.iterations = iterations
        self.wall_clock_s = wall_clock_s
        self.tokens = tokens


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


class LLMUnderstandingBuilder:
    """LLM-driven UnderstandingOfTarget from the interview transcript (PR5 / C1).

    When an Ollama client is available the Coordinator reads the operator interview
    transcript + locked target scope and produces a structured understanding —
    instead of the deterministic keyword/TLD heuristics. Returns ``None`` to signal
    the caller should fall back to the deterministic builder (no client, model
    unreachable, or unparseable output).
    """

    SYSTEM_PROMPT = """\
You are the Coordinator of the OSA penetration-testing platform. Read the operator
interview transcript and the locked target scope, then output ONLY a JSON object:
{"target_kind": "web_app|network|cloud|mobile|unknown",
 "detected_stack": ["..."], "entry_points": ["..."], "constraints": ["..."]}.
Ground every field in the transcript + target. Never list hosts outside the scope."""

    async def build(
        self, transcript: list[dict], target: dict, client: Any
    ) -> "UnderstandingOfTarget | None":
        import json

        from app.orchestrator.model_client import ModelUnreachable
        from app.orchestrator.roles.llm_provider import resolve_role_send_model

        convo = "\n".join(
            f"{m.get('role', '?')}: {m.get('content', '')}" for m in transcript
        )
        user = (
            f"Target scope: {json.dumps(target)}\n\n"
            f"Interview transcript:\n{convo}\n\n"
            "Produce the UnderstandingOfTarget JSON."
        )
        try:
            resp = await client.send(
                model_id=resolve_role_send_model(None),
                messages=[{"role": "user", "content": user}],
                system=self.SYSTEM_PROMPT,
            )
            data = json.loads((resp.text or "{}").strip())
        except (ModelUnreachable, json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        fallback_entries = list(target.get("domains", [])) + list(target.get("ip_ranges", []))
        return UnderstandingOfTarget(
            target_kind=str(data.get("target_kind", "unknown")),
            detected_stack=[str(s) for s in (data.get("detected_stack") or [])],
            entry_points=[str(e) for e in (data.get("entry_points") or [])] or fallback_entries,
            constraints=[str(c) for c in (data.get("constraints") or [])],
            raw_signals={"source": "llm_interview", "transcript_turns": len(transcript)},
        )


class CoordinatorService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._u = UnderstandingBuilder()
        self._p = PlanOfWorkBuilder()
        self._llm_u = LLMUnderstandingBuilder()

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

    async def build_understanding(
        self,
        *,
        prompt: str,
        target: dict,
        transcript: list[dict] | None = None,
        model_client: Any = None,
    ) -> UnderstandingOfTarget:
        """Build the UnderstandingOfTarget.

        LLM-driven from the interview transcript when a client is resolvable
        (injected, or Ollama via ``osa_llm_provider="ollama"``); the deterministic
        ``UnderstandingBuilder`` is the fallback (keeps replay byte-identical when no
        client / no transcript is available).
        """
        from app.orchestrator.roles.llm_provider import resolve_role_client

        client = resolve_role_client(model_client)
        if client is not None and transcript:
            llm = await self._llm_u.build(transcript, target, client)
            if llm is not None:
                return llm
        return await self._u.build(prompt, target)

    async def run_interview_turn(
        self,
        *,
        session: Any,
        user_content: str,
        model_client: Any = None,
    ) -> Any:
        """Advance the operator interview by ONE turn via the AmbiguityLoop
        (turn-based, LLM-driven / Ollama-capable, ambiguity-gated).

        Lease invariant (PR5 BLOCKING fix): this NEVER acquires a ``_PerformerLease``.
        The interview runs OUTSIDE the lease — each turn is a discrete message-endpoint
        request that returns — so a session mid-interview cannot starve the per-session
        Performer concurrency cap. The lease is taken only once the interview
        terminates (``ready_for_review``) and dispatch begins.
        """
        from app.orchestrator.ambiguity_loop import AmbiguityLoop

        loop = AmbiguityLoop(self._db, model_client=model_client)
        return await loop.run_turn(session, user_content)

    def derive_plan_of_work(self, understanding: UnderstandingOfTarget) -> PlanOfWork:
        """Understanding-driven PlanOfWork (PR6 / C3).

        Derives ordered_phases + family_recommendations from the understanding's
        target_kind/AttackVector — so a web_app target yields web-flavored phases +
        palette and a network target yields network-flavored ones (NOT the hardcoded
        constant). The deterministic PlanOfWorkBuilder keeps its constant phases for
        byte-identical replay; this drives the autonomous lane.
        """
        from app.orchestrator.roles.seed_xbow import (
            coerce_vector,
            vector_to_phases,
            vector_to_tool_palette,
        )

        vector = coerce_vector(understanding.target_kind)
        palette = list(vector_to_tool_palette.get(vector, []))
        phases = list(vector_to_phases.get(vector, ["recon"]))
        families = [
            {"family_kind": "discovery", "vector": vector.value,
             "palette": palette[:2], "rationale": "scope the surface first"},
            {"family_kind": "attack", "vector": vector.value,
             "palette": palette, "rationale": f"{vector.value} attack family"},
        ]
        return PlanOfWork(
            objectives=[f"Assess {vector.value} target via {', '.join(phases)}"],
            family_recommendations=families,
            ordered_phases=phases,
            success_criteria=[f"findings reported for the {vector.value} surface"],
        )

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

    async def run_with_iteration_cap(
        self,
        *,
        session_id,
        prompt,
        target,
        actor_id,
        lane,
        replay_opt_in=False,
        token_counter_fn=None,
        clock_fn=None,
    ):
        """Iterate Coordinator.run up to settings caps, monotonically bumping iteration_no.

        Args:
          token_counter_fn: callable returning total tokens consumed so far (default: lambda: 0)
          clock_fn: callable returning current monotonic wall-clock seconds (default: time.monotonic)

        Raises:
          IterationCapHit on first cap trip. Persists session.status='failed'
          via audit before raising. Calling code may catch and react.
        """
        import time
        from app.core.config import settings
        token_counter_fn = token_counter_fn or (lambda: 0)
        clock_fn = clock_fn or time.monotonic

        start = clock_fn()
        iteration_no = 0
        last_understanding = None
        last_plan_of_work = None

        while True:
            iteration_no += 1
            if iteration_no > settings.max_coordinator_iterations:
                await self._audit_cap_hit(session_id, actor_id, "max_iterations",
                    iteration_no - 1, clock_fn() - start, token_counter_fn())
                raise IterationCapHit("max_iterations",
                    iterations=iteration_no - 1,
                    wall_clock_s=clock_fn() - start,
                    tokens=token_counter_fn())

            elapsed = clock_fn() - start
            if elapsed > settings.max_coordinator_wall_clock_seconds:
                await self._audit_cap_hit(session_id, actor_id, "max_wall_clock",
                    iteration_no - 1, elapsed, token_counter_fn())
                raise IterationCapHit("max_wall_clock",
                    iterations=iteration_no - 1, wall_clock_s=elapsed,
                    tokens=token_counter_fn())

            tokens = token_counter_fn()
            if tokens > settings.max_coordinator_total_tokens:
                await self._audit_cap_hit(session_id, actor_id, "max_total_tokens",
                    iteration_no - 1, clock_fn() - start, tokens)
                raise IterationCapHit("max_total_tokens",
                    iterations=iteration_no - 1, wall_clock_s=clock_fn() - start,
                    tokens=tokens)

            last_understanding, last_plan_of_work = await self.run(
                session_id=session_id, prompt=prompt, target=target,
                actor_id=actor_id, lane=lane, replay_opt_in=replay_opt_in,
            )
            # Single-pass deterministic builders: one iteration is enough.
            # The loop exists to be tripped by adversarial fixtures that
            # try to make the coordinator iterate (PR4.3); under normal
            # operation we break after iteration_no=1.
            break

        return (last_understanding, last_plan_of_work, iteration_no)

    async def _audit_cap_hit(self, session_id, actor_id, reason, iterations, wall_clock_s, tokens):
        audit_logger = AuditLogger(self._db)
        await audit_logger.log(
            action="coordinator.iteration_cap_hit",
            actor_id=actor_id,
            target_entity="pentest_session",
            target_id=str(session_id),
            details={
                "reason": reason,
                "iterations": iterations,
                "wall_clock_s": wall_clock_s,
                "tokens": tokens,
            },
        )
