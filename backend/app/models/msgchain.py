"""MsgChain model (v4.0 P1) — per-role conversation transcript persisted to Postgres.

PentAGI parallel: `pentagi/backend/pkg/providers/performer.go` uses an enum
`MsgchainType` and persists chains to a `msgchains` table. OSA adopts the
pattern as an OSA-strong hybrid (per v4.0 ADR-005).

One MsgChain row = one role's conversation chain inside one PentestSession.
- `role_name` ∈ {"generator", "pentester", "memorist", "adviser", "reflector",
  "reporter"} for the Minimal 6 roles in v4.0; v3.4 may extend this enum.
- `messages_json` is a JSONB list of message dicts with shape:
    `{"role": "user"|"assistant"|"tool", "content": str, "tool_use_id": str|None,
      "usage": {"input_tokens": int, "output_tokens": int}|None, "timestamp": iso8601}`
- `retries` increments each time the Reflector wrap re-runs this chain after a
  transient failure (capped at `settings.reflector_max_retries`, default 3).

Schema-disjointness invariant (P1 SF-2): keys present in
`messages_json[*]` MUST NOT overlap with keys present in
`PentestSession.draft_plan_json.steps[*]`. The invariant is enforced by
`backend/tests/unit/test_msgchain_no_subtask_overlap.py`.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class MsgChain(Base, UUIDMixin):
    __tablename__ = "msgchains"

    pentest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    messages_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running"
    )
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    session: Mapped["PentestSession"] = relationship(back_populates="msgchains")
