import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentFamilyInstance(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agent_family_instances"

    pentest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_family_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_family_instances.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", nullable=False, index=True
    )
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
