"""Workflow service — chat-driven plan drafting + state machine (plan v3.2.1 §4).

State transitions (subset, P3 scope):
    draft → interviewing
    interviewing → ready_for_review   (ambiguity ≤ threshold OR force-approve)
    interviewing → needs_human_review (turn_count ≥ max_turns)
    ready_for_review → approved | rejected
    approved → executing (handed to executor — P4)

The model is asked to return a strict JSON envelope on every assistant turn:

    {
      "ambiguity": 0.0..1.0,
      "blockers": ["unspecified target scope", ...],
      "reasoning": "...",
      "draft_plan": {
          "target_summary": "...",
          "risk_level": "low|medium|high",
          "steps": [{"order": 1, "agent": "...", "action": "...", ...}]
      }
    }

The sanity guard (``min_required_fields_present``) overrides a low model
ambiguity ONLY when required fields are missing (Critic D-3 mitigation).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Project, Target
from app.models.session import PentestSession, WorkflowMessage
from app.models.user import User, UserRole
from app.observability.metrics import ambiguity_bucket, metrics
from app.orchestrator.model_client import ModelClient, ModelUnreachable
from app.orchestrator.model_selector import ModelId, ModelSelector
from app.safety.audit import AuditLogger
from app.safety.whitelist import WhitelistValidator


CHAT_SYSTEM_PROMPT = """You are an AI security orchestrator drafting an authorized penetration testing plan.

You converse with a senior operator. Every turn you must respond with a single JSON object exactly matching this schema:

{
  "ambiguity": <float in [0.0, 1.0] — your honest assessment of how under-specified the plan still is>,
  "blockers": [<short strings naming unsatisfied predicates>],
  "reasoning": "<one-paragraph explanation of what is still ambiguous>",
  "draft_plan": {
    "target_summary": "<brief description of the target environment>",
    "risk_level": "low|medium|high",
    "steps": [
      {"order": <int>, "agent": "<tool slug>", "action": "<intent slug>", "description": "<one-line>", "config": {}, "tier": "<one of: passive_no_target_contact|passive_low_touch|active_recon|active_exploit>"}
    ]
  }
}

Rules:
- Only include steps that are authorized and within the operator's project whitelist.
- Prefer low-risk reconnaissance before high-risk steps.
- Never include DoS, ransomware, or data-destruction steps.
- If the operator's intent is unclear, set ambiguity ≥ 0.5 and explain in blockers.
- If the operator's intent is clear and the plan is complete, set ambiguity ≤ 0.3.

Respond ONLY with valid JSON, no markdown code fences."""


@dataclass(frozen=True)
class AssistantTurn:
    """Parsed model response."""

    ambiguity: float
    blockers: list[str]
    reasoning: str
    draft_plan: dict


@dataclass(frozen=True)
class MessageResult:
    user_message: WorkflowMessage
    assistant_message: WorkflowMessage
    new_state: str
    interview_turn_count: int
    ambiguity_score: Decimal


@dataclass(frozen=True)
class ApprovalPreview:
    is_valid: bool
    violations: list[str]
    step_count: int


# ── State machine ───────────────────────────────────────────────────────────

_INTERVIEW_STATES = {"draft", "interviewing"}
_TERMINAL_AFTER_REVIEW = {"ready_for_review"}


def _ensure_session(session: PentestSession | None, session_id: uuid.UUID) -> PentestSession:
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session


def _ensure_state(session: PentestSession, allowed: set[str]) -> None:
    if session.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Session state '{session.status}' does not allow this action; expected one of {sorted(allowed)}",
        )


def _parse_assistant_text(text: str) -> AssistantTurn:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model returned non-JSON response: {exc}",
        )
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="Model response not an object")
    ambiguity = float(obj.get("ambiguity", 1.0))
    if not (0.0 <= ambiguity <= 1.0):
        ambiguity = max(0.0, min(1.0, ambiguity))
    blockers = list(obj.get("blockers") or [])
    reasoning = str(obj.get("reasoning") or "")
    draft_plan = obj.get("draft_plan") or {}
    if not isinstance(draft_plan, dict):
        draft_plan = {}
    return AssistantTurn(
        ambiguity=ambiguity,
        blockers=blockers,
        reasoning=reasoning,
        draft_plan=draft_plan,
    )


def min_required_fields_present(draft_plan: dict) -> bool:
    """Sanity guard (Critic D-3 mitigation).

    The chat may not advance to ``ready_for_review`` until the draft plan has
    a non-empty target_summary, a risk_level, and ≥ 1 step each carrying an
    agent + intent slug + tier.
    """
    if not isinstance(draft_plan, dict):
        return False
    if not draft_plan.get("target_summary"):
        return False
    if draft_plan.get("risk_level") not in {"low", "medium", "high"}:
        return False
    steps = draft_plan.get("steps") or []
    if not steps:
        return False
    for step in steps:
        if not isinstance(step, dict):
            return False
        if not (step.get("agent") and step.get("action") and step.get("tier")):
            return False
    return True


def _next_state_after_turn(turn: AssistantTurn, new_turn_count: int) -> str:
    if not min_required_fields_present(turn.draft_plan):
        # sanity guard overrides any low-ambiguity claim from the model
        if new_turn_count >= settings.workflow_max_interview_turns:
            return "needs_human_review"
        return "interviewing"
    if turn.ambiguity <= settings.workflow_ambiguity_threshold:
        return "ready_for_review"
    if new_turn_count >= settings.workflow_max_interview_turns:
        return "needs_human_review"
    return "interviewing"


# ── Service ─────────────────────────────────────────────────────────────────


class WorkflowService:
    def __init__(
        self,
        db: AsyncSession,
        model_selector: ModelSelector | None = None,
        model_client: ModelClient | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._db = db
        self._selector = model_selector or ModelSelector()
        self._client = model_client  # lazy-init in send_message if None
        self._audit = audit or AuditLogger(db)

    # ── creation ─────────────────────────────────────────────────────────

    async def create_draft(
        self,
        *,
        project_id: uuid.UUID,
        initial_prompt: str,
        user: User,
        model_id: str | None = None,
        domain_agent_slug: str | None = None,
    ) -> PentestSession:
        result = await self._db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        resolved = self._selector.resolve(model_id, user)

        session = PentestSession(
            project_id=project_id,
            prompt=initial_prompt,
            status="draft",
            interview_state="not_started",
            interview_turn_count=0,
            ambiguity_score=Decimal("1.000"),
            model_id=resolved.model_id,
            domain_agent_slug=domain_agent_slug,
            team_id=user.team_id,
            draft_plan_json={},
        )
        self._db.add(session)
        await self._db.flush()
        return session

    # ── chat ─────────────────────────────────────────────────────────────

    async def send_message(
        self,
        *,
        session_id: uuid.UUID,
        user_message: str,
        user: User,
    ) -> MessageResult:
        session = await self._fetch(session_id)
        _ensure_state(session, _INTERVIEW_STATES | {"interview_paused"})

        if session.interview_turn_count >= settings.workflow_max_interview_turns:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Interview turn cap ({settings.workflow_max_interview_turns}) reached; "
                    "use /force-ready-for-review or /reject"
                ),
            )

        if session.status == "draft":
            session.status = "interviewing"
            session.interview_state = "interviewing"

        turn_index = session.interview_turn_count

        # 1) persist user turn
        user_msg = WorkflowMessage(
            pentest_session_id=session.id,
            role="user",
            content=user_message,
            turn_index=turn_index,
        )
        self._db.add(user_msg)
        await self._db.flush()

        # 2) build full chat history for ModelClient
        prior = await self._db.execute(
            select(WorkflowMessage)
            .where(WorkflowMessage.pentest_session_id == session.id)
            .order_by(WorkflowMessage.turn_index.asc(), WorkflowMessage.created_at.asc())
        )
        history: list[dict] = []
        for m in prior.scalars().all():
            history.append({"role": m.role, "content": m.content})

        # 3) call model
        client = self._client or ModelClient()
        try:
            response = await client.send(
                model_id=self._resolved_anthropic_id(session.model_id),
                messages=history,
                system=CHAT_SYSTEM_PROMPT,
            )
        except ModelUnreachable as exc:
            session.status = "interview_paused"
            session.interview_state = "interview_paused"
            session.resume_token = uuid.uuid4()
            await self._db.flush()
            await self._audit.log(
                action="claude_api_unreachable",
                actor_id=str(user.id),
                target_entity="pentest_session",
                target_id=str(session.id),
                details={"error": str(exc), "resume_token": str(session.resume_token)},
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "claude_api_unreachable",
                    "resume_token": str(session.resume_token),
                    "message": str(exc),
                },
            )

        # 4) parse + state transition
        turn = _parse_assistant_text(response.text)
        new_count = session.interview_turn_count + 1
        new_state = _next_state_after_turn(turn, new_count)

        ambiguity_decimal = Decimal(f"{turn.ambiguity:.3f}")

        asst_msg = WorkflowMessage(
            pentest_session_id=session.id,
            role="assistant",
            content=response.text,
            turn_index=turn_index,
            ambiguity_after=ambiguity_decimal,
            blockers_json={"items": turn.blockers, "reasoning": turn.reasoning},
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
        )
        self._db.add(asst_msg)

        session.draft_plan_json = turn.draft_plan
        session.ambiguity_score = ambiguity_decimal
        session.interview_turn_count = new_count
        session.status = new_state
        session.interview_state = (
            "ready_for_review" if new_state == "ready_for_review"
            else "needs_human_review" if new_state == "needs_human_review"
            else "interviewing"
        )
        await self._db.flush()

        # ── observability hooks (P5) ────────────────────────────────────
        metrics.session_interview_turns_total.inc(outcome=new_state)
        metrics.session_ambiguity_score.inc(bucket=ambiguity_bucket(turn.ambiguity))
        metrics.anthropic_tokens_total.inc(
            value=response.tokens_in, model=session.model_id, phase="input",
        )
        metrics.anthropic_tokens_total.inc(
            value=response.tokens_out, model=session.model_id, phase="output",
        )
        if session.domain_agent_slug:
            metrics.domain_agent_dispatch_total.inc(
                domain=session.domain_agent_slug, result=new_state,
            )
        await self._audit.log(
            action="session_message_sent",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session.id),
            details={
                "turn_index": turn_index,
                "ambiguity": turn.ambiguity,
                "new_state": new_state,
                "tokens_in": response.tokens_in,
                "tokens_out": response.tokens_out,
            },
        )
        await self._audit.log(
            action="draft_plan_updated",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session.id),
            details={"ambiguity": turn.ambiguity, "blockers": turn.blockers},
        )

        return MessageResult(
            user_message=user_msg,
            assistant_message=asst_msg,
            new_state=new_state,
            interview_turn_count=new_count,
            ambiguity_score=ambiguity_decimal,
        )

    # ── force ready for review ───────────────────────────────────────────

    async def force_ready_for_review(
        self,
        *,
        session_id: uuid.UUID,
        override_reason: str,
        user: User,
    ) -> PentestSession:
        if len(override_reason) < settings.workflow_force_approve_min_reason_chars:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"override_reason must be ≥ "
                    f"{settings.workflow_force_approve_min_reason_chars} characters"
                ),
            )
        session = await self._fetch(session_id)
        _ensure_state(session, _INTERVIEW_STATES | {"needs_human_review"})

        if not session.draft_plan_json:
            raise HTTPException(
                status_code=409,
                detail="Cannot force-ready a session with no draft plan",
            )

        session.status = "ready_for_review"
        session.interview_state = "ready_for_review"
        session.ambiguity_override_at = datetime.now(timezone.utc)
        session.ambiguity_override_by = user.id
        session.ambiguity_override_reason = override_reason
        await self._db.flush()
        await self._audit.log(
            action="ambiguity_override",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session.id),
            details={
                "reason": override_reason,
                "ambiguity_at_override": float(session.ambiguity_score or 1.0),
            },
        )
        return session

    # ── approval preview ────────────────────────────────────────────────

    async def approval_preview(self, *, session_id: uuid.UUID) -> ApprovalPreview:
        session = await self._fetch(session_id)
        _ensure_state(session, _TERMINAL_AFTER_REVIEW)
        target = await self._project_target(session.project_id)
        validator = WhitelistValidator(target.whitelist_rules if target else {})
        violations = _collect_violations(session.draft_plan_json or {}, validator)
        return ApprovalPreview(
            is_valid=not violations,
            violations=violations,
            step_count=len((session.draft_plan_json or {}).get("steps") or []),
        )

    # ── approve ─────────────────────────────────────────────────────────

    async def approve(
        self,
        *,
        session_id: uuid.UUID,
        user: User,
    ) -> PentestSession:
        session = await self._fetch(session_id)
        _ensure_state(session, _TERMINAL_AFTER_REVIEW)

        preview = await self.approval_preview(session_id=session_id)
        if not preview.is_valid:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "out_of_scope",
                    "violations": preview.violations,
                },
            )

        now = datetime.now(timezone.utc)
        session.status = "approved"
        session.approved_at = now
        session.approved_by = user.id
        # Promote the draft to the canonical plan; execute step is handled by P4 executor.
        session.plan_json = session.draft_plan_json
        await self._db.flush()

        # P5: time-to-ready metric
        if session.created_at is not None:
            created = session.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            elapsed = (now - created).total_seconds()
            if elapsed >= 0:
                metrics.session_time_to_ready_for_review_seconds.observe(elapsed)

        await self._audit.log(
            action="session_approved",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session.id),
            details={"step_count": len((session.plan_json or {}).get("steps") or [])},
        )
        return session

    async def reject(
        self,
        *,
        session_id: uuid.UUID,
        user: User,
    ) -> PentestSession:
        session = await self._fetch(session_id)
        _ensure_state(session, _TERMINAL_AFTER_REVIEW | {"needs_human_review"})
        session.status = "rejected"
        session.interview_state = "needs_human_review"
        session.ended_at = datetime.now(timezone.utc)
        await self._db.flush()
        await self._audit.log(
            action="session_rejected",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session.id),
            details={},
        )
        return session

    # ── helpers ─────────────────────────────────────────────────────────

    async def _fetch(self, session_id: uuid.UUID) -> PentestSession:
        result = await self._db.execute(
            select(PentestSession).where(PentestSession.id == session_id)
        )
        return _ensure_session(result.scalar_one_or_none(), session_id)

    async def _project_target(self, project_id: uuid.UUID) -> Target | None:
        result = await self._db.execute(
            select(Target).where(Target.project_id == project_id)
        )
        return result.scalars().first()

    def _resolved_anthropic_id(self, model_id: str) -> str:
        if model_id == settings.anthropic_default_model:
            return settings.anthropic_default_model_anthropic_id
        if model_id == settings.anthropic_admin_model:
            return settings.anthropic_admin_model_anthropic_id
        return model_id  # passthrough for tests using raw IDs


# ── module-level utility used by approve + approval_preview ────────────────


def _collect_violations(draft_plan: dict, validator: WhitelistValidator) -> list[str]:
    violations: list[str] = []
    seen: set[str] = set()
    for step in (draft_plan.get("steps") or []):
        cfg = step.get("config") or {}
        # candidate target fields inside step config
        ips = cfg.get("ip_ranges") or ([cfg["target"]] if "target" in cfg and _looks_like_ip(cfg["target"]) else [])
        domains = cfg.get("domains") or (
            [cfg["target"]] if "target" in cfg and not _looks_like_ip(cfg["target"]) else []
        )
        host = cfg.get("host")
        if host:
            if _looks_like_ip(host):
                ips = [*ips, host]
            else:
                domains = [*domains, host]
        for ip in ips:
            if ip in seen:
                continue
            seen.add(ip)
            if not validator.validate_ip(ip):
                violations.append(f"step {step.get('order')}: IP out of scope: {ip}")
        for d in domains:
            d = (d or "").lower()
            if not d or d in seen:
                continue
            seen.add(d)
            if not validator.validate_domain(d):
                violations.append(f"step {step.get('order')}: domain out of scope: {d}")
    return violations


def _looks_like_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False
