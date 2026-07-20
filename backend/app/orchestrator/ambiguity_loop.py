"""AmbiguityLoop — Generator-driven clarification loop (v4.0 P4).

Drives the `Generator` role across multiple turns. Each turn:
1. Compose context (initial prompt + prior turns + RAG hits from Memorist).
2. Call Generator.run() — returns an envelope
   `{ambiguity, blockers, reasoning, draft_plan}`.
3. Persist a `WorkflowMessage` row with the turn outcome.
4. Persist a `MsgChain` row scoped to the `generator` role.
5. Transition `interview_state` per the same rules as
   `workflow_service._next_state_after_turn`:
   - ambiguity > threshold AND turn_count < max → keep `interviewing`
   - ambiguity > threshold AND turn_count >= max → `needs_human_review`
   - ambiguity ≤ threshold → `ready_for_review`

Activation: `WorkflowService.send_message` re-routes through this loop when
`settings.osa_flow_ui_enabled=True`. Flag OFF preserves the v3.2.1 path.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import palette_text
from app.core.config import settings
from app.models.msgchain import MsgChain
from app.models.session import PentestSession, WorkflowMessage
from app.orchestrator.memorist_auto_call import auto_inject
from app.orchestrator.roles.generator import Generator


@dataclass
class AmbiguityTurnResult:
    """Outcome of one AmbiguityLoop turn."""

    ambiguity: float
    blockers: list[str]
    reasoning: str
    draft_plan: dict[str, Any]
    next_state: str
    # True when the envelope was truncated/partially-invalid and only its early
    # scalar fields (ambiguity/blockers/reasoning) were regex-salvaged — the
    # draft_plan was NOT adopted from this turn (the prior draft is preserved).
    salvaged: bool = False


def _decide_next_state(ambiguity: float, turn_count: int) -> str:
    """v4.0 P4 transition rules — mirror `_next_state_after_turn` in v3.2.1."""
    if ambiguity <= settings.workflow_ambiguity_threshold:
        return "ready_for_review"
    if turn_count >= settings.workflow_max_interview_turns:
        return "needs_human_review"
    return "interviewing"


class AmbiguityLoop:
    """One turn of the Generator-driven clarification loop."""

    def __init__(
        self,
        db: AsyncSession,
        model_client: Any = None,
        client_factory: Any = None,
        send_model_id: str | None = None,
    ) -> None:
        self._db = db
        # Optional injection — when provided, Generator runs live against
        # Anthropic. When None, Generator returns its deterministic envelope
        # (used by unit tests that exercise AmbiguityLoop in isolation).
        self._model_client = model_client
        # Per-session provider routing (interview lane): when a ``client_factory``
        # is supplied the Generator resolves its client via the session's provider
        # (Copilot/Ollama/…) instead of the injected model_client, and
        # ``send_model_id`` forces the provider-coherent model so the send is not
        # coupled to the GLOBAL provider switch. Both stay None on the injected/
        # test path → byte-identical.
        self._client_factory = client_factory
        self._send_model_id = send_model_id

    async def run_turn(
        self,
        session: PentestSession,
        user_content: str,
    ) -> AmbiguityTurnResult:
        """Execute one Generator turn against `user_content` and persist outcomes.

        Returns the envelope + the next interview_state. Caller is responsible
        for committing the DB transaction.
        """
        # 1. Memorist auto-call — pull RAG hits for the user message.
        memory_hits = await auto_inject(self._db, user_content)

        # 2. Build the chat history for Generator — mirrors `workflow_service`
        #    pattern (workflow_service.py:288). Generator uses the history to
        #    keep continuity across interview turns.
        from sqlalchemy import select

        prior = await self._db.execute(
            select(WorkflowMessage)
            .where(WorkflowMessage.pentest_session_id == session.id)
            .order_by(
                WorkflowMessage.turn_index.asc(),
                WorkflowMessage.created_at.asc(),
            )
        )
        history = [
            {"role": m.role, "content": m.content} for m in prior.scalars().all()
        ]

        # 2b. Build the REAL tool palette so the Generator grounds its draft
        #     plan in registered slugs/actions/tiers (not invented names). Mirror
        #     the catalog's kali_* visibility filter via osa_kali_backend_enabled.
        tools_palette = palette_text(settings.osa_kali_backend_enabled)

        # 3. Generator.run() — live Anthropic call when `model_client` was
        #    injected at construction, otherwise the deterministic envelope.
        gen = Generator()
        gen_result = await gen.run(
            performer=None,
            context={
                "user_content": user_content,
                "memory_hits": memory_hits,
                "history": history,
                "model_client": self._model_client,
                "send_model_id": self._send_model_id,
                "tools_palette": tools_palette,
            },
            client_factory=self._client_factory,
        )

        # 3. Parse the envelope from the smoke message. P4 hardens this with
        #    JSON parsing from the live LLM response.
        envelope_text = gen_result.messages[0]["content"] if gen_result.messages else "{}"
        envelope = self._parse_envelope(envelope_text)

        salvaged = bool(envelope.pop("_salvaged", False))
        ambiguity = float(envelope.get("ambiguity", 1.0))
        blockers = list(envelope.get("blockers", []))
        reasoning = str(envelope.get("reasoning", ""))
        # Draft-plan guard (session 0f9c5646 regression): a truncated /
        # unparseable / draft-less envelope must NOT wipe a previously-good draft
        # with an empty skeleton — that empty draft is what let a 0-step plan
        # reach approval. Adopt a NEW draft ONLY when the parse produced the
        # `draft_plan` key (a clean parse — which may legitimately carry an empty
        # steps list on an intentional high-ambiguity clear); on a salvaged or
        # parse-failed envelope (key absent) PRESERVE the prior draft_plan_json.
        new_draft = envelope.get("draft_plan")
        if isinstance(new_draft, dict):
            draft_plan = dict(new_draft)
        else:
            draft_plan = dict(session.draft_plan_json or {"steps": []})

        # 4. Persist WorkflowMessage row for the assistant turn.
        new_turn_count = session.interview_turn_count + 1
        next_state = _decide_next_state(ambiguity, new_turn_count)

        msg = WorkflowMessage(
            pentest_session_id=session.id,
            role="assistant",
            content=envelope_text,
            turn_index=new_turn_count,
            ambiguity_after=Decimal(str(round(ambiguity, 3))),
            blockers_json={"items": blockers} if blockers else None,
        )
        self._db.add(msg)

        # 5. Persist MsgChain row scoped to the generator role.
        chain = MsgChain(
            pentest_session_id=session.id,
            role_name="generator",
            messages_json=[
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": envelope_text},
            ],
            started_at=datetime.now(timezone.utc),
            status="finished",
        )
        self._db.add(chain)

        # 6. Update session counters + state.
        session.interview_turn_count = new_turn_count
        session.ambiguity_score = Decimal(str(round(ambiguity, 3)))
        session.interview_state = next_state
        session.draft_plan_json = draft_plan

        await self._db.flush()
        return AmbiguityTurnResult(
            ambiguity=ambiguity,
            blockers=blockers,
            reasoning=reasoning,
            draft_plan=draft_plan,
            next_state=next_state,
            salvaged=salvaged,
        )

    @staticmethod
    def _parse_envelope(text: str) -> dict[str, Any]:
        """Best-effort parse with truncation salvage.

        Order: strict JSON → the P2a smoke shape (`str(dict)`) → regex salvage of
        the early scalar fields → parse-failed sentinel. The interview envelope
        emits ``ambiguity`` + ``blockers`` + ``reasoning`` BEFORE the (large)
        ``draft_plan``, so those survive a max_tokens truncation even when the
        trailing JSON is cut off (session 0f9c5646: a 13KB turn truncated
        mid-draft and collapsed to ambiguity 1.0, sticking the interview).

        A salvaged or sentinel envelope deliberately OMITS ``draft_plan`` so
        ``run_turn`` preserves the prior good draft instead of adopting a
        truncated / empty plan.
        """
        import json

        raw = text.strip()
        # Strip a code fence if the LLM wrapped its JSON (tolerate a MISSING
        # closing fence — a truncated response has an opening ``` but no close).
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw[3:]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        try:
            # P2a smoke returns `str(dict)` — eval-safe via literal_eval.
            import ast

            data = ast.literal_eval(raw)
            if isinstance(data, dict):
                return data
        except (ValueError, SyntaxError):
            pass
        salvaged = AmbiguityLoop._salvage_scalars(raw)
        if salvaged is not None:
            return salvaged
        return {"ambiguity": 1.0, "blockers": ["envelope_parse_failed"], "reasoning": ""}

    @staticmethod
    def _salvage_scalars(text: str) -> dict[str, Any] | None:
        """Recover ambiguity / blockers / reasoning from a truncated envelope.

        Returns a dict marked ``_salvaged`` and WITHOUT a ``draft_plan`` key (the
        caller preserves the prior draft), or ``None`` when no top-level
        ``ambiguity`` field is present → the caller's parse-failed sentinel. The
        recovered ``blockers`` are faithful (no synthetic marker): the raw turn
        text is stored verbatim on the WorkflowMessage, and the salvage is
        recorded via the ``ambiguity_loop_turn`` audit (``salvaged: true``).
        """
        import json
        import re

        m = re.search(r'"ambiguity"\s*:\s*(-?\d+(?:\.\d+)?)', text)
        if not m:
            return None
        out: dict[str, Any] = {"ambiguity": float(m.group(1)), "_salvaged": True}

        blockers: list[str] = []
        bm = re.search(r'"blockers"\s*:\s*(\[[^\]]*\])', text)
        if bm:
            try:
                arr = json.loads(bm.group(1))
                if isinstance(arr, list):
                    blockers = [str(x) for x in arr]
            except json.JSONDecodeError:
                pass
        out["blockers"] = blockers

        rm = re.search(r'"reasoning"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if rm:
            try:
                out["reasoning"] = json.loads('"' + rm.group(1) + '"')
            except json.JSONDecodeError:
                out["reasoning"] = rm.group(1)
        return out
