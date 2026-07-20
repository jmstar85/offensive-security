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

import copy
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.agent_family import AgentFamilyInstance
from app.models.msgchain import MsgChain
from app.models.oob import OOBCallback
from app.models.project import Project, Target
from app.models.report import Report
from app.models.session import (
    AgentExecution,
    AttackScenario,
    PentestSession,
    RescopeApproval,
    TerminalLine,
    WorkflowMessage,
)
from app.models.user import User
from app.observability.metrics import ambiguity_bucket, metrics
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.model_client import ModelClient, ModelUnreachable
from app.orchestrator.model_selector import ModelSelector
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
- Keep draft_plan a CONCISE skeleton: AT MOST 8 high-level steps with one-line
  descriptions (a downstream planner expands it into the full run). Always populate
  each step's `config` (target/host/ip_ranges/domains) so the scope preview can
  validate it — trim only prose, never the config.
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


def interview_ambiguity_target() -> float:
    """The ambiguity ceiling the interview must reach before ready_for_review.

    Group B: when ``osa_interview_autoblock_enabled`` is on, the flow interview
    uses the tighter autoblock target (the "until ≤ 20%" contract); otherwise the
    legacy ``workflow_ambiguity_threshold`` (0.35) applies.
    """
    if getattr(settings, "osa_interview_autoblock_enabled", False):
        return settings.osa_interview_autoblock_threshold
    return settings.workflow_ambiguity_threshold


def _next_state_after_turn(turn: AssistantTurn, new_turn_count: int) -> str:
    if not min_required_fields_present(turn.draft_plan):
        # sanity guard overrides any low-ambiguity claim from the model
        if new_turn_count >= settings.workflow_max_interview_turns:
            return "needs_human_review"
        return "interviewing"
    if turn.ambiguity <= interview_ambiguity_target():
        return "ready_for_review"
    if new_turn_count >= settings.workflow_max_interview_turns:
        return "needs_human_review"
    return "interviewing"


def resolve_interview_model(session: PentestSession) -> str:
    """Cheap PER-PROVIDER interview/chat model (Blocking 1 / Principle 6c).

    Decoupled from ``session.model_id`` (never promoted to opus-4-8) and coherent
    with the interview PROVIDER, so an Ollama-only session never receives an
    Anthropic id (which would be garbage to ``OllamaClient``) and "Ollama never
    prompts" holds. Provider comes from ``session.llm_provider_pref`` (the single
    provider field, Finding 6); when NULL it falls back to the global
    ``settings.osa_llm_provider`` switch (Principle 10) — anthropic ⇒ sonnet-4-6,
    so legacy interview behavior is byte-identical.
    """
    provider = getattr(session, "llm_provider_pref", None) or settings.osa_llm_provider
    if provider == "ollama":
        return settings.ollama_model
    if provider == "openai":
        return settings.openai_interview_model
    if provider == "copilot":
        # The operator picks a specific Copilot model from the live catalog; honor
        # THAT selection for the interview (user requirement) rather than forcing
        # the cheap default. Only fall back to the default when the selection is
        # unset or not a Copilot-namespaced id.
        selected = getattr(session, "model_id", None)
        if selected and str(selected).startswith("copilot/"):
            return selected
        return getattr(settings, "github_copilot_default_model", "copilot/gpt-4o")
    # anthropic (and any unrecognized provider) → cheap Anthropic default
    return settings.anthropic_default_model


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
        model_map: dict[str, str] | None = None,
        mode: str = "automation",
        provider: str | None = None,
        template_id: str | None = None,
    ) -> PentestSession:
        result = await self._db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        # Gap 1 (provider-aware): HONOR the client's session-model selection.
        # The ModelSelector catalog is Anthropic-only (opus-4-8 default /
        # sonnet-4-6 selectable / admin-gated opus-4-6), so it can only validate
        # Anthropic ids. Run it — for RBAC (unknown→400, admin-only opus-4-6 for a
        # non-admin→403) and the documented session default (opus-4-8 when the
        # client omits model_id) — ONLY when the session provider is Anthropic (or
        # unset, which defaults to Anthropic). For ollama/openai the model_id is
        # that provider's own id (e.g. qwen3-14b-96k:latest, gpt-4o) and is NOT in
        # the Anthropic catalog; routing it through resolve() would wrongly 400 the
        # primary Ollama-default flow. Trust the provider's model_id there (per-role
        # model_map values are likewise provider-specific and uncatalogued).
        if provider in (None, "anthropic"):
            resolved_model_id = self._selector.resolve(
                model_id or settings.session_default_model, user
            ).model_id
        else:
            from app.orchestrator.roles.llm_provider import (  # noqa: PLC0415
                default_model_for,
            )

            resolved_model_id = model_id or default_model_for(provider)

        # Gap 2: a workflow-template selection SEEDS the deterministic saved-
        # workflow lane. The template's steps/edges (agents.py — single source of
        # truth) map directly into the plan_json shape normalize_workflow_plan /
        # PlanExecutor consume, so a non-empty plan_json flips the service.py lane
        # gate ("saved_workflow" if session.plan_json else "fresh_plan") to the
        # deterministic PlanExecutor. Seed BOTH plan_json AND draft_plan_json:
        # approve() promotes draft_plan_json → plan_json, so seeding draft_plan_json
        # is what makes the template survive the create → approve → launch flow.
        template_plan: dict | None = None
        if template_id is not None:
            from app.api.v1.agents import get_workflow_template  # noqa: PLC0415

            template = get_workflow_template(template_id)
            if template is None:
                raise HTTPException(
                    status_code=400, detail=f"Unknown template_id: {template_id}"
                )
            template_plan = {
                "version": 1,
                "kind": "workflow",
                "steps": copy.deepcopy(template.get("steps", [])),
                "edges": copy.deepcopy(template.get("edges", [])),
            }

        session = PentestSession(
            project_id=project_id,
            prompt=initial_prompt,
            status="draft",
            interview_state="not_started",
            interview_turn_count=0,
            ambiguity_score=Decimal("1.000"),
            # Gap 1: the RBAC-validated client selection (opus-4-8 by default,
            # or the client's model_id when provided) — consumed by
            # ModelSelector/session.model_id to route the autonomous engine
            # roles. The interview/chat turn is resolved per-provider via
            # resolve_interview_model (never promoted to opus).
            model_id=resolved_model_id,
            domain_agent_slug=domain_agent_slug,
            team_id=user.team_id,
            # Gap 2: a template selection seeds BOTH plan_json (flips the lane
            # gate to deterministic immediately) and draft_plan_json (so approve's
            # draft→plan promotion keeps the template). No template ⇒ unchanged
            # (plan_json=None → fresh-plan/autonomous lane; draft_plan_json={}).
            plan_json=copy.deepcopy(template_plan) if template_plan else None,
            draft_plan_json=copy.deepcopy(template_plan) if template_plan else {},
            # New-flow additive fields (PR1). `provider` (when present) is the
            # selector's provider choice, persisted as llm_provider_pref
            # (single provider field, Finding 6); NULL preserves the
            # global-switch fallback. The operator objective is the draft
            # prompt (the Path-B objective box == the draftPrompt textarea).
            model_map=model_map or {},
            mode=mode,
            llm_provider_pref=provider,
            objective=initial_prompt,
        )
        self._db.add(session)
        await self._db.flush()
        return session

    # ── chat ─────────────────────────────────────────────────────────────

    async def _persist_interview_paused(
        self,
        *,
        session_id: uuid.UUID,
        resume_token: uuid.UUID,
        audit_action: str,
        actor_id: str,
        audit_details: dict,
    ) -> None:
        """Persist the ``interview_paused`` marker on a SEPARATE short-lived
        committed session so it survives the ``get_db`` rollback (plan R21).

        The interview send endpoint runs under ``get_db`` (``core/database.py``),
        which rolls back the request session on ANY raised exception. Writing
        ``interview_paused`` on ``self._db`` and then raising the 503 would be
        rolled back with everything else, so the paused banner could never
        replay. The paused marker (+ its audit row) is therefore committed on
        its OWN session here, before the caller raises the 503.

        ``self._db`` is rolled back FIRST so it releases the row lock it holds on
        the ``pentest_sessions`` row (from the in-turn user-message flush);
        otherwise this side-session UPDATE would block on that uncommitted lock
        within the same event-loop task and hang.
        """
        await self._db.rollback()
        async with async_session() as side_db:
            row = await side_db.get(PentestSession, session_id)
            if row is not None:
                row.status = "interview_paused"
                row.interview_state = "interview_paused"
                row.resume_token = resume_token
            await AuditLogger(side_db).log(
                action=audit_action,
                actor_id=actor_id,
                target_entity="pentest_session",
                target_id=str(session_id),
                details=audit_details,
            )
            await side_db.commit()

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

        # v4.0 P4 flag-gated branch — route the chat turn through AmbiguityLoop
        # (Generator role + Memorist auto-call + msgchain persistence) when
        # `osa_flow_ui_enabled` is True. OFF path (default) falls through to
        # the v3.2.1 ModelClient call unchanged so all 223 baseline tests stay
        # green without flipping the flag.
        if settings.osa_flow_ui_enabled:
            from app.orchestrator.ambiguity_loop import AmbiguityLoop

            # Route the interview turn to the SESSION'S provider — no longer
            # hardcoded to Anthropic (the bug: a Copilot/Ollama session got a
            # ModelClient() with no ANTHROPIC_API_KEY → 500 "Could not resolve
            # authentication method"). Three cases, in precedence order:
            #   1. TEST-injected client (self._client set) → keep the prior
            #      behavior so every existing flag-ON test that injects a stub
            #      stays byte-identical.
            #   2. multi-provider ON → build the per-session client_factory +
            #      provider-coherent send model, exactly like the autonomous lane
            #      (build_client_factory → resolve_session_role_client →
            #      LLMRouter.route(session provider, user)). A missing credential
            #      propagates from the factory as CredentialNotFound and is handled
            #      by the except below.
            #   3. legacy single-provider → the v4.0 hardcoded ModelClient path.
            if self._client is not None:
                loop = AmbiguityLoop(db=self._db, model_client=self._client)
            elif settings.osa_multi_provider_llm:
                from app.orchestrator.roles.llm_provider import (  # noqa: PLC0415
                    build_client_factory,
                )

                factory = build_client_factory(
                    db=self._db, session=session, actor_id=str(user.id)
                )
                # resolve_interview_model returns the cheap per-provider interview
                # model (copilot→github_copilot_default_model, ollama→ollama_model,
                # …), coherent with the provider the factory routes to.
                send_model_id = self._resolved_anthropic_id(
                    resolve_interview_model(session)
                )
                loop = AmbiguityLoop(
                    db=self._db, client_factory=factory, send_model_id=send_model_id
                )
            else:
                loop = AmbiguityLoop(db=self._db, model_client=ModelClient())
            try:
                turn_result = await loop.run_turn(session, user_content=user_message)
            except CredentialNotFound as exc:
                # Graceful credential failure (plan A4): pause + 503 instead of a
                # raw 500, persisted across the get_db rollback (R21).
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="interview_credential_required",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "credential_required",
                        "resume_token": str(resume_token),
                        "message": (
                            "The selected LLM provider has no stored credential. "
                            "Connect the provider (for example GitHub Copilot) in "
                            "settings, then resume the interview."
                        ),
                    },
                )
            except ModelUnreachable as exc:
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="claude_api_unreachable",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "claude_api_unreachable",
                        "resume_token": str(resume_token),
                        "message": str(exc),
                    },
                )
            except HTTPException:
                # A graceful HTTPException raised inside the loop already carries
                # its status + detail — never re-wrap it as a 503 below.
                raise
            except Exception as exc:  # noqa: BLE001
                # Final safety net: ANY other provider/config failure (e.g. an
                # unexpected auth error from a misconfigured provider) becomes a
                # graceful, PERSISTED 503 pause instead of a raw 500 — so the
                # interview never 500s again. Mirrors the ModelUnreachable handler.
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="interview_error",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "interview_error",
                        "resume_token": str(resume_token),
                        "message": str(exc),
                    },
                )
            # Fetch the assistant turn AmbiguityLoop just persisted.
            asst_q = await self._db.execute(
                select(WorkflowMessage)
                .where(WorkflowMessage.pentest_session_id == session.id)
                .order_by(WorkflowMessage.turn_index.desc(), WorkflowMessage.created_at.desc())
                .limit(1)
            )
            asst_msg = asst_q.scalar_one()
            await self._audit.log(
                action="ambiguity_loop_turn",
                actor_id=str(user.id),
                target_entity="pentest_session",
                target_id=str(session.id),
                details={
                    "ambiguity": turn_result.ambiguity,
                    "blockers": turn_result.blockers,
                    "next_state": turn_result.next_state,
                    "salvaged": turn_result.salvaged,
                },
            )
            return MessageResult(
                user_message=user_msg,
                assistant_message=asst_msg,
                new_state=turn_result.next_state,
                interview_turn_count=session.interview_turn_count,
                ambiguity_score=session.ambiguity_score,
            )

        # 2) build full chat history for ModelClient
        prior = await self._db.execute(
            select(WorkflowMessage)
            .where(WorkflowMessage.pentest_session_id == session.id)
            .order_by(WorkflowMessage.turn_index.asc(), WorkflowMessage.created_at.asc())
        )
        history: list[dict] = []
        for m in prior.scalars().all():
            history.append({"role": m.role, "content": m.content})

        # 3) call model — route through LLMRouter when multi-provider flag is ON
        if settings.osa_multi_provider_llm:
            from app.orchestrator.llm.router import LLMRouter  # noqa: PLC0415
            from app.orchestrator.llm.context import get_current_user_id  # noqa: PLC0415

            # Interview PROVIDER + MODEL are both taken per-provider from
            # session.llm_provider_pref (NULL ⇒ global switch, Principle 10), so
            # they stay coherent and are DECOUPLED from session.model_id: an
            # ollama session routes OllamaClient with qwen3-14b (never an
            # Anthropic id), and an opus-4-8 session never runs opus here
            # (Blocking 1 / PM3).
            _provider = getattr(session, "llm_provider_pref", None) or settings.osa_llm_provider
            _user_id = getattr(session, "actor_id", None) or get_current_user_id()
            try:
                # route() resolves the per-user credential (credential_resolver)
                # BEFORE the send, so it lives INSIDE the try: a missing
                # credential raises CredentialNotFound here (plan A4), and must
                # map to the same graceful 503 pause as an unreachable model.
                _llm_client = await LLMRouter().route(
                    db=self._db,
                    provider=_provider,
                    user_id=_user_id,
                )
                response = await _llm_client.send(
                    model_id=self._resolved_anthropic_id(resolve_interview_model(session)),
                    messages=history,
                    system=CHAT_SYSTEM_PROMPT,
                )
            except CredentialNotFound as exc:
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="interview_credential_required",
                    actor_id=str(user.id),
                    audit_details={
                        "error": str(exc),
                        "provider": _provider,
                        "resume_token": str(resume_token),
                    },
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "credential_required",
                        "resume_token": str(resume_token),
                        "message": (
                            f"The selected LLM provider ({_provider}) has no stored "
                            "credential. Connect the provider (for example GitHub "
                            "Copilot) in settings, then resume the interview."
                        ),
                    },
                )
            except ModelUnreachable as exc:
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="claude_api_unreachable",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "claude_api_unreachable",
                        "resume_token": str(resume_token),
                        "message": str(exc),
                    },
                )
        else:
            client = self._client or ModelClient()
            try:
                response = await client.send(
                    model_id=self._resolved_anthropic_id(resolve_interview_model(session)),
                    messages=history,
                    system=CHAT_SYSTEM_PROMPT,
                )
            except CredentialNotFound as exc:
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="interview_credential_required",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "credential_required",
                        "resume_token": str(resume_token),
                        "message": (
                            "The selected LLM provider has no stored credential. "
                            "Connect the provider (for example GitHub Copilot) in "
                            "settings, then resume the interview."
                        ),
                    },
                )
            except ModelUnreachable as exc:
                resume_token = uuid.uuid4()
                await self._persist_interview_paused(
                    session_id=session.id,
                    resume_token=resume_token,
                    audit_action="claude_api_unreachable",
                    actor_id=str(user.id),
                    audit_details={"error": str(exc), "resume_token": str(resume_token)},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "claude_api_unreachable",
                        "resume_token": str(resume_token),
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
        # Label token metrics with the model actually used for THIS interview
        # turn (resolve_interview_model — per-provider, decoupled from
        # session.model_id), not the opus-4-8 session/engine default.
        _interview_model = resolve_interview_model(session)
        metrics.session_interview_turns_total.inc(outcome=new_state)
        metrics.session_ambiguity_score.inc(bucket=ambiguity_bucket(turn.ambiguity))
        metrics.anthropic_tokens_total.inc(
            value=response.tokens_in, model=_interview_model, phase="input",
        )
        metrics.anthropic_tokens_total.inc(
            value=response.tokens_out, model=_interview_model, phase="output",
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

        # Gate on real STEPS, not merely a truthy dict: a wiped/parse-failed turn
        # leaves a truthy-but-empty {"steps": []} that slipped past the old
        # `if not session.draft_plan_json` check and let a 0-step plan proceed
        # (session 0f9c5646). This is the SOLE status→ready_for_review setter on
        # the interview bug path, so the guard is load-bearing.
        if not _draft_has_steps(session.draft_plan_json):
            raise HTTPException(status_code=409, detail=dict(_EMPTY_PLAN_DETAIL))

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
        approval_flags: dict | None = None,
    ) -> PentestSession:
        session = await self._fetch(session_id)
        _ensure_state(session, _TERMINAL_AFTER_REVIEW)

        # Refuse to approve a session with no runnable plan. The scope preview
        # below is blind to step COUNT (a 0-step plan has 0 violations → valid),
        # so a wiped interview draft would otherwise approve into a no-op
        # "completed" run (session 0f9c5646). A pre-seeded executable plan_json
        # (template lane) satisfies the guard even when the chat draft is empty.
        if not _draft_has_steps(session.draft_plan_json) and not (
            session.plan_json or {}
        ).get("steps"):
            raise HTTPException(status_code=409, detail=dict(_EMPTY_PLAN_DETAIL))

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
        # Persist the operator's tier approval choices alongside the approval
        # event. The orchestrator's filter_by_tier_flags consumes this dict.
        if approval_flags is not None:
            session.approval_flags = {
                k: bool(v) for k, v in approval_flags.items()
            }
        # Promote the draft to the canonical plan ONLY when it is already an
        # executable workflow (template-seeded: steps carry `id` + executable
        # agents). A chat-shaped interview draft ({order,agent,action,tier}, no
        # `id`, tool-slug agents) is display metadata, not a runnable plan:
        # promoting it flips the service.py lane gate to "saved_workflow", whose
        # normalize_workflow_plan then rejects the chat steps and fails the run.
        # Leaving plan_json unchanged keeps a template session's pre-seeded
        # plan_json (deterministic lane) and keeps a fresh-plan (interview)
        # session's plan_json None → the autonomous lane runs (as the driver does).
        from app.orchestrator.workflow_plan import (  # noqa: PLC0415
            WorkflowPlanError,
            normalize_workflow_plan,
        )

        draft = session.draft_plan_json or {}
        if draft:
            try:
                normalize_workflow_plan(draft)
            except WorkflowPlanError:
                pass  # chat-shaped interview draft — do NOT promote
            else:
                session.plan_json = draft
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

    async def delete_session(
        self,
        *,
        session_id: uuid.UUID,
        user: User,
    ) -> None:
        """Permanently delete a session and all of its child rows.

        Every direct child of ``pentest_sessions`` is deleted explicitly, then
        the session row itself. This is deterministic and DB-portable: three
        children (``agent_executions``, ``attack_scenarios``, ``reports``) carry
        a plain FK with no ``ON DELETE CASCADE``, so they MUST be removed before
        the session; the rest cascade in production Postgres but we delete them
        explicitly too so the behaviour does not depend on DB-level cascade
        enforcement (SQLite in tests does not enforce it). All nine children are
        leaf tables (nothing references their own id), so a flat delete-by-
        session is complete. ``terminal_lines`` → ``agent_executions`` is
        ``ON DELETE SET NULL`` and never blocks.
        """
        session = await self._fetch(session_id)
        # Team scoping — surface a 404 (not 403) so we don't leak that a
        # session belongs to another team.
        if session.team_id is not None and user.team_id != session.team_id:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        # A live run owns a container + background task; deleting its rows
        # mid-flight would strand both. Require it to finish or be rejected.
        if session.status == "running":
            raise HTTPException(
                status_code=409,
                detail="Cannot delete a running session; wait for it to finish or reject it first.",
            )
        prev_status = session.status
        # Children keyed by session_id …
        for model in (TerminalLine, AgentExecution, AttackScenario, Report):
            await self._db.execute(delete(model).where(model.session_id == session_id))
        # … and children keyed by pentest_session_id.
        for model in (WorkflowMessage, RescopeApproval, MsgChain, OOBCallback, AgentFamilyInstance):
            await self._db.execute(
                delete(model).where(model.pentest_session_id == session_id)
            )
        await self._db.delete(session)
        await self._db.flush()
        await self._audit.log(
            action="session_deleted",
            actor_id=str(user.id),
            target_entity="pentest_session",
            target_id=str(session_id),
            details={"prev_status": prev_status},
        )

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
        if model_id == settings.session_default_model:
            return settings.session_default_model_anthropic_id
        if model_id == settings.anthropic_default_model:
            return settings.anthropic_default_model_anthropic_id
        if model_id == settings.anthropic_admin_model:
            return settings.anthropic_admin_model_anthropic_id
        return model_id  # passthrough for tests using raw IDs


# ── module-level utility used by approve + approval_preview ────────────────


def _draft_has_steps(draft_plan: dict | None) -> bool:
    """True when the draft plan carries at least one step.

    A truthy-but-empty ``{"steps": []}`` (what a wiped/parse-failed interview turn
    used to leave behind — session 0f9c5646) is NOT a runnable plan; approving it
    yields a no-op "completed" run. The chokepoints below gate on this instead of
    a bare ``if not draft_plan`` (which a non-empty dict slips past).
    """
    if not isinstance(draft_plan, dict):
        return False
    steps = draft_plan.get("steps")
    return isinstance(steps, list) and bool(steps)


_EMPTY_PLAN_DETAIL = {
    "error": "empty_plan",
    "message": (
        "This session has no plan steps. Continue the interview until it "
        "produces at least one step, or start from a workflow template."
    ),
}


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
