"""OOBCallback — out-of-band (Interactsh) callback correlated to a session (PR8 / C5)."""
import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class OOBCallback(Base, UUIDMixin, TimestampMixin):
    """An inbound OOB callback (DNS/HTTP/SMTP) whose canary token verified against
    a specific session — the substrate for confirming OOB-XSS/SSRF exploitation."""

    __tablename__ = "oob_callbacks"

    pentest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)  # dns|http|smtp
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    canary_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
