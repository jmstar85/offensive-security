"""Assistant mode: role-free interactive turn service (PR7 / Option B1').

``AssistantService.turn`` drives ONE operator turn as a thin, role-free loop that
reuses the ENTIRE existing safety envelope through the ONE sanctioned dispatch
chokepoint — it never adds a second execution path and never adds a new reachable
role (inbound or outbound):

- **No new inbound role.** The Assistant is NOT ``register_role``'d
  (``assistant ∉ ROLE_REGISTRY``), so a chain role emitting ``{"tool":"assistant"}``
  invokes no loop (PM2-D-in).
- **No new outbound role primitive.** The loop dispatches via
  ``delegate_tool_call(..., allow_role_invocation=False)`` — the default-deny
  chokepoint refuses any ``ROLE_REGISTRY`` slug the operator's model emits
  (``{"tool":"pentester"}`` etc.), so it can never launch a role as a sub-role
  (PM2-D-out / Finding 3 / Improvement 2).
- **Same safety chain.** A bound ``Performer`` (``bind_live_execution``) runs the
  per-dispatch tier/exploit/risk filter trio + runtime ``EgressMonitor`` inside
  ``_dispatch_tool``; the turn runs inside ``Performer._concurrency_guard()`` (the
  ADR-003 lease); the shared ``validate_session_target`` scope gate runs once
  before the first dispatch — identical to Automation.
- **Single-sourced parser.** The loop parses the model envelope via the shared
  ``parse_tool_envelope`` (Improvement 1), so malformed / injection envelopes are
  rejected identically to the Pentester.
- **Per-session turn mutex.** A second concurrent turn on one session is refused
  (409), so exactly one live turn holds the per-session lease (Principle 4a).
- **Fail-closed.** The Assistant client is resolved PER TURN via
  ``resolve_session_role_client`` (no session cache); a missing credential
  propagates ``CredentialNotFound`` — never a smoke fixture — on this bound live lane.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import list_agent_types
from app.core.config import settings
from app.core.events import event_bus
from app.models.msgchain import MsgChain
from app.models.project import Target
from app.models.session import PentestSession
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.model_client import ModelUnreachable
from app.orchestrator.performer import Performer, PerformerConcurrencyLimit
from app.orchestrator.roles.llm_provider import (
    context_is_bound_live,
    default_model_for,
    resolve_role_send_model,
    resolve_session_role_client,
)
from app.orchestrator.runtime_delegator import delegate_tool_call
from app.orchestrator.scope import validate_session_target
from app.orchestrator.tool_envelope import parse_tool_envelope
from app.safety.audit import AuditLogger


ASSISTANT_SYSTEM_PROMPT = """\
You are the Assistant of the OSA platform: an interactive, operator-driven
security co-pilot. Execute the operator's request by emitting structured tool
calls of the form:

    {"tool": "<tool_slug>", "intent": "<intent_slug>", "config": {...}}

where `tool_slug` is one of the available tools. The platform dispatches each
call through the SAME safety chain as autonomous mode (whitelist → exploit
allowlist → tier gate → risk filter → egress monitor → kill switch). You MUST
NOT emit raw shell commands and you MUST NOT name another agent/role as a tool —
only real tools are dispatchable. When the request is complete, emit
`{"done": true, "summary": "<why complete>"}`. To ask the operator a question,
emit `{"tool": "ask", "intent": "<question>"}`.
"""


class AssistantTurnInProgress(Exception):
    """A turn is already in flight for this session (per-session mutex, 409)."""


class AssistantModeError(Exception):
    """The session is not in ``assistant`` mode (409)."""


class AssistantSessionNotFound(Exception):
    """No such session (404)."""


@dataclass
class AssistantTurnResult:
    content: str
    session_id: uuid.UUID
    scope_violation: bool = False


# ── Per-session turn mutex (Principle 4a) ────────────────────────────────────
# Module-level so it survives across requests within one uvicorn worker. A second
# turn on a session with a turn in-flight is REFUSED (not queued) so exactly one
# live turn per session holds the per-session ADR-003 lease.
_turn_locks: dict[uuid.UUID, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


async def _acquire_turn_lock(session_id: uuid.UUID) -> asyncio.Lock:
    """Acquire the per-session turn lock non-blockingly, or raise 409.

    The registry lock serializes the check-then-acquire so two concurrent turns
    on one session cannot both observe an unlocked lock. Acquiring a free
    ``asyncio.Lock`` completes without suspending, so this holds no lock across an
    await that could interleave another acquirer.
    """
    async with _registry_lock:
        lock = _turn_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise AssistantTurnInProgress("turn in progress")
        await lock.acquire()
    return lock


def _compact(result: dict) -> dict:
    """Trim a dispatch result to the fields the model needs for its next move."""
    return {
        k: result.get(k)
        for k in ("approved", "blocked_reason", "executed", "findings",
                  "killed", "egress_violation", "paused_for_rescope")
        if k in result
    }


class AssistantService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._audit = AuditLogger(db)

    async def turn(
        self, session_id: uuid.UUID | str, content: str, user: Any
    ) -> AssistantTurnResult:
        """Run exactly one Assistant turn. Raises 409-mapped exceptions on a
        concurrent turn or a non-assistant session."""
        session_id = uuid.UUID(str(session_id))
        lock = await _acquire_turn_lock(session_id)  # 409 if in-flight
        try:
            return await self._run_turn(session_id, content, user)
        finally:
            lock.release()

    async def _run_turn(
        self, session_id: uuid.UUID, content: str, user: Any
    ) -> AssistantTurnResult:
        actor_id = str(user.id)

        session = (
            await self._db.execute(
                select(PentestSession).where(PentestSession.id == session_id)
            )
        ).scalar_one_or_none()
        if session is None:
            raise AssistantSessionNotFound(str(session_id))
        if session.mode != "assistant":
            raise AssistantModeError("not assistant mode")

        # Load target + whitelist (same source Automation reads).
        target_obj = (
            await self._db.execute(
                select(Target).where(Target.project_id == session.project_id)
            )
        ).scalars().first()
        target = {
            "ip_ranges": target_obj.ip_ranges if target_obj else [],
            "domains": target_obj.domains if target_obj else [],
        }
        whitelist_rules = target_obj.whitelist_rules if target_obj else {}

        # Persist the operator turn to the Assistant MsgChain (accumulated below).
        transcript: list[dict[str, Any]] = [{"role": "user", "content": content}]

        # Build a BOUND Performer so _dispatch_tool runs the per-dispatch tier gate
        # + seeds the runtime EgressMonitor — identical to Automation.
        performer = Performer(self._db, session_id)
        performer.bind_live_execution(
            target=target,
            approval_flags=session.approval_flags or {},
            whitelist_rules=whitelist_rules,
            actor_id=actor_id,
        )
        performer.state.context["objective"] = content

        # Shared session-start scope gate — ONCE before the first dispatch.
        is_valid, violations = validate_session_target(target, whitelist_rules)
        if not is_valid:
            await self._audit.log(
                action="whitelist_violation",
                actor_id=actor_id,
                target_entity="pentest_session",
                target_id=str(session_id),
                details={"violations": violations},
            )
            text = f"[scope violation] session target out of scope: {violations}"
            transcript.append({"role": "assistant", "content": text})
            await self._persist_chain(session_id, transcript)
            await self._publish(session_id, text)
            await self._db.commit()
            return AssistantTurnResult(
                content=text, session_id=session_id, scope_violation=True
            )

        # Resolve the Assistant client PER TURN (no session cache — Blocking 2);
        # a missing credential propagates CredentialNotFound (never smoke).
        client = await resolve_session_role_client(
            self._db, session, "assistant", user_id=user.id
        )
        if client is None and context_is_bound_live(performer):
            raise CredentialNotFound(
                "no LLM client resolved for the Assistant on the bound live lane "
                "(fail-closed: never smoke on a live turn)"
            )

        model_id = self._resolve_send_model(session)
        max_steps = int(getattr(settings, "assistant_max_steps_per_turn", 16))
        palette = ", ".join(sorted(list_agent_types()))
        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": (
                f"Objective: {content}\n\n"
                f"Tools available: {palette}\n\n"
                "Emit exactly ONE JSON tool call per turn as "
                '{"tool": "<slug>", "intent": "<intent>", "config": {...}} or '
                '{"done": true, "summary": "<why complete>"}.'
            ),
        }]

        final_text = ""
        steps = 0
        # One turn inside the ADR-003 per-session lease (PM2-C). The per-session
        # mutex guarantees exactly one live turn holds this lease.
        try:
            async with performer._concurrency_guard():
                while True:
                    if steps >= max_steps:
                        final_text = "[capped] step cap reached"
                        transcript.append({"role": "assistant", "content": final_text})
                        break
                    try:
                        response = await client.send(
                            model_id=model_id,
                            messages=messages,
                            system=ASSISTANT_SYSTEM_PROMPT,
                        )
                    except ModelUnreachable as exc:
                        final_text = f"[error] model_unreachable: {exc}"
                        transcript.append({"role": "assistant", "content": final_text})
                        break

                    raw = (response.text or "").strip()
                    transcript.append({"role": "assistant", "content": raw})

                    parsed = parse_tool_envelope(raw)  # single-sourced (Improvement 1)
                    if parsed.parse_error is not None:
                        final_text = f"[{parsed.parse_error}]"
                        transcript.append({"role": "assistant", "content": final_text})
                        break
                    if parsed.is_done:
                        final_text = f"[done] {parsed.summary}"
                        transcript.append({"role": "assistant", "content": final_text})
                        break
                    if parsed.is_ask:
                        final_text = f"[ask] {parsed.ask_text}"
                        transcript.append({"role": "assistant", "content": final_text})
                        break

                    # Dispatch through the ONE sanctioned chokepoint with outbound
                    # role-invocation DENIED (allow_role_invocation=False): an
                    # operator-emitted ROLE_REGISTRY slug is refused, not launched.
                    delegated = await delegate_tool_call(
                        performer, parsed.slug, parsed.payload,
                        allow_role_invocation=False,
                    )
                    steps += 1
                    result = (
                        delegated.get("result", {}) if isinstance(delegated, dict) else {}
                    )
                    transcript.append({
                        "role": "tool",
                        "content": f"{parsed.slug}: approved={result.get('approved')} "
                                   f"reason={result.get('blocked_reason', 'ok')}",
                    })
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": f"Tool result for {parsed.slug}: "
                                   f"{json.dumps(_compact(result))[:1000]}",
                    })
        except PerformerConcurrencyLimit as exc:
            final_text = f"[error] concurrency_limit: {exc}"
            transcript.append({"role": "assistant", "content": final_text})

        await self._persist_chain(session_id, transcript)
        await self._publish(session_id, final_text)
        await self._db.commit()
        return AssistantTurnResult(content=final_text, session_id=session_id)

    def _resolve_send_model(self, session: PentestSession) -> str:
        """Model id to pass to the resolved client's ``.send()``, per the same
        provider/model precedence ``resolve_session_role_client`` uses."""
        model_map = getattr(session, "model_map", None) or {}
        override = model_map.get("assistant")
        if override:
            return override
        if session.llm_provider_pref is not None:
            return session.model_id or default_model_for(session.llm_provider_pref)
        return resolve_role_send_model(None)  # NULL → global-switch send model

    async def _persist_chain(
        self, session_id: uuid.UUID, transcript: list[dict[str, Any]]
    ) -> None:
        now = datetime.now(timezone.utc)
        chain = MsgChain(
            pentest_session_id=session_id,
            role_name="assistant",
            messages_json=list(transcript),
            started_at=now,
            ended_at=now,
            status="finished",
        )
        self._db.add(chain)
        await self._db.flush()

    async def _publish(self, session_id: uuid.UUID, content: str) -> None:
        await event_bus.publish(
            str(session_id),
            {"type": "assistant_message", "role": "assistant", "content": content},
            topic="conversation",
        )
