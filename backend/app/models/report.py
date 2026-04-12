import uuid

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Report(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pentest_sessions.id"), nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    session: Mapped["PentestSession"] = relationship(back_populates="reports")
