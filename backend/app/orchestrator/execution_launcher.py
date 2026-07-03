"""Shared autonomous-execution launcher (PR5 / PM1 / FLAG 1 / Finding 4).

One sanctioned launcher both the legacy ``/sessions/`` path (Path A) and the
redesigned ``/pentest-sessions/`` approve path (Path B) reach the autonomous
engine through, so the PM1 per-user credential-context wrap
(``with_user_context``) and (in PR6) per-role routing are applied at a single,
provably-covered site rather than one of two divergent subsystems.

The launcher matches ``OrchestratorService.run``'s real signature exactly
(``run(session_id, prompt, actor_id)``): ``svc.run`` loads the session itself,
seeds ``context["objective"] = prompt``, and reaches the ``service.py`` lane
gate (``lane == "fresh_plan"``) which decides autonomous vs. deterministic —
the launcher never bypasses that gate.
"""
from __future__ import annotations

import uuid

from app.core.database import async_session
from app.orchestrator.llm.context import with_user_context
from app.orchestrator.service import OrchestratorService


async def launch_autonomous_execution(session_id, prompt: str, actor_id) -> None:
    """Open one DB session, wrap it in the actor's credential context, and run.

    ``session_id`` / ``actor_id`` are coerced to ``uuid.UUID`` (str-vs-UUID
    coercion at the boundary, Principle 5) so ``credential_resolver`` never
    compares a ``str`` against the UUID column. ``prompt`` is passed positionally
    to ``svc.run`` — it becomes ``context["objective"]`` for the autonomous lane.
    """
    session_id = uuid.UUID(str(session_id))
    actor_id = uuid.UUID(str(actor_id))
    async with async_session() as db:  # single spawn site
        with with_user_context(actor_id):  # PM1 wrap, UUID-typed
            svc = OrchestratorService(db)
            await svc.run(session_id, prompt, actor_id)
