"""Shared terminal-line persistence buffer for the /flow Terminal replay (migration 013).

Both orchestrator lanes stream adapter stdout as ``AgentEvent(event_type="log")``
through a per-step ``_publish_event`` closure:
    - deterministic lane: ``app/orchestrator/executor.py`` (``PlanExecutor.execute``)
    - autonomous lane:     ``app/orchestrator/performer.py`` (``_execute_step_through_helper``)

``TerminalLineSink`` is the ONE implementation both closures share so the buffering /
seq / bulk-insert logic is not duplicated. Each run/closure constructs its own sink
instance (holding its own buffer); ``seq`` is DB-derived so it stays monotonic across
steps and closures.

Seq assignment
--------------
Each line gets a per-SESSION monotonic ``seq``. The counter is seeded ONCE per sink from
``SELECT coalesce(max(seq), 0) FROM terminal_lines WHERE session_id=:sid`` (the
authoritative DB max) on the first buffered line, then incremented in memory. Because the
orchestrator writes one session's steps sequentially — and each fresh per-step sink
re-seeds from the DB after the previous step committed — ``seq`` stays correct across
steps/closures/sinks. The SAME assigned ``seq`` is BOTH returned to the closure (published
at the top level of the live ``log`` event) AND persisted, so the frontend can de-dupe the
history/live boundary on ``seq`` (the live value must equal the stored value, which is why
seq is fixed at buffer time rather than renumbered at flush).

Durability
----------
Lines are bulk-inserted (``db.add_all`` + ``flush``) every ``FLUSH_THRESHOLD`` buffered
lines; the remainder is flushed when the caller sees a terminal ``status`` event
(completed/failed) and again after the adapter stream ends. Rows are flushed onto the
orchestrator's SHARED session — NOT committed here — for two reasons: (1) ``execution_id``
FK-references the ``AgentExecution`` row the same run just created but has not committed, so
only the shared session can satisfy the FK at insert time (a separate session cannot see the
uncommitted parent → the insert would be dropped); (2) committing mid-run would close the
caller's transaction, breaking the deterministic byte-identical replay harness that drives
``PlanExecutor.execute`` inside an outer ``session.begin()``. The orchestrator commits the
shared session at its existing phase/role boundaries (``service.py`` after each lane,
``_persist_msgchain_end`` after each role), which is what makes these rows visible to the
separate-session history GET on reload — the LIVE Terminal panel meanwhile renders straight
off the WS ``terminal`` topic. Every DB touch is wrapped so a failure logs and is swallowed:
observability must never break the run, and a dropped tail under load is acceptable.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TerminalLineSink:
    """Per-run buffer that bulk-persists streamed stdout lines to ``terminal_lines``."""

    FLUSH_THRESHOLD = 25

    def __init__(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        self._db = db
        self._session_id = session_id
        self._buffer: list[dict] = []
        # Lazily seeded from the DB max on the first line so the seq stays
        # monotonic across steps/closures without a query per line.
        self._next_seq: int | None = None

    async def _ensure_seed(self) -> None:
        if self._next_seq is not None:
            return
        from app.models.session import TerminalLine

        result = await self._db.execute(
            select(func.coalesce(func.max(TerminalLine.seq), 0)).where(
                TerminalLine.session_id == self._session_id
            )
        )
        self._next_seq = int(result.scalar_one()) + 1

    async def add(
        self,
        *,
        execution_id: uuid.UUID | None,
        agent_type: str | None,
        line: str,
    ) -> int | None:
        """Buffer one log line, assign + return its per-session ``seq``, flush if full.

        Returns the assigned ``seq`` so the caller can publish it at the top level of
        the live event, or ``None`` if seeding/buffering failed (the caller then
        publishes without a ``seq`` — a dropped tail is acceptable).
        """
        try:
            await self._ensure_seed()
            assert self._next_seq is not None
            seq = self._next_seq
            self._next_seq += 1
            self._buffer.append(
                {
                    "seq": seq,
                    "execution_id": execution_id,
                    "agent_type": agent_type,
                    "line": line,
                }
            )
            if len(self._buffer) >= self.FLUSH_THRESHOLD:
                await self.flush()
            return seq
        except Exception:  # noqa: BLE001 — persistence must never break the run.
            logger.exception(
                "TerminalLineSink.add failed for session=%s (non-fatal)",
                self._session_id,
            )
            return None

    async def flush(self) -> None:
        """Bulk-insert the buffered lines onto the shared session (no commit — the
        orchestrator commits at its phase/role boundaries). Defensive: never raises."""
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        try:
            from app.models.session import TerminalLine

            self._db.add_all(
                [
                    TerminalLine(
                        session_id=self._session_id,
                        execution_id=row["execution_id"],
                        seq=row["seq"],
                        agent_type=row["agent_type"],
                        line=row["line"],
                    )
                    for row in batch
                ]
            )
            await self._db.flush()
        except Exception:  # noqa: BLE001 — a dropped tail is acceptable under load.
            logger.exception(
                "TerminalLineSink.flush dropped %d line(s) for session=%s (non-fatal)",
                len(batch),
                self._session_id,
            )
