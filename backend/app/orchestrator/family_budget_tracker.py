"""Per-family per-session token tracker — W4/PR4.4.

The Coordinator/Performer call into this module after each Role turn
to attribute tokens-in + tokens-out to the family that consumed them.
Output is surfaced via Prometheus (family_tokens_total) AND the
/pentest-sessions/{id}/agent-families endpoint (which adds a
tokens_consumed field per family row).
"""
from __future__ import annotations
import uuid
from collections import defaultdict
from app.observability.metrics import family_tokens_total


class FamilyBudgetTracker:
    def __init__(self):
        self._counts: dict[tuple[uuid.UUID, str], int] = defaultdict(int)

    def record(self, session_id: uuid.UUID, family_kind: str, tokens: int) -> None:
        key = (session_id, family_kind)
        self._counts[key] += tokens
        family_tokens_total.inc(
            float(tokens),
            session_id=str(session_id),
            family_kind=family_kind,
        )

    def get(self, session_id: uuid.UUID, family_kind: str) -> int:
        return self._counts.get((session_id, family_kind), 0)

    def snapshot(self, session_id: uuid.UUID) -> dict[str, int]:
        return {fk: cnt for (sid, fk), cnt in self._counts.items() if sid == session_id}


tracker = FamilyBudgetTracker()
