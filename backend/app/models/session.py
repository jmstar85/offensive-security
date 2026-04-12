import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class PentestSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pentest_sessions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="sessions")
    executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="session", cascade="all, delete"
    )
    scenarios: Mapped[list["AttackScenario"]] = relationship(
        back_populates="session", cascade="all, delete"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="session", cascade="all, delete"
    )


class AgentExecution(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agent_executions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pentest_sessions.id"), nullable=False
    )
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[PentestSession] = relationship(back_populates="executions")


class AttackScenario(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "attack_scenarios"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pentest_sessions.id"), nullable=False
    )
    steps_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_assessment: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    session: Mapped[PentestSession] = relationship(back_populates="scenarios")
