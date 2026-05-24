import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
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

    # --- Workflow-draft schema (migration 003) -------------------------------
    domain_agent_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str] = mapped_column(
        String(64), default="claude-sonnet-4-6", nullable=False
    )
    draft_plan_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    interview_state: Mapped[str] = mapped_column(
        String(32), default="not_started", nullable=False
    )
    interview_turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ambiguity_score: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), default=Decimal("1.000"), nullable=False
    )
    ambiguity_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ambiguity_override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    ambiguity_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    cost_usd_accum: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("0"), nullable=False
    )
    paused_for_rescope_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rescope_request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resume_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True
    )

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
    workflow_messages: Mapped[list["WorkflowMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="WorkflowMessage.turn_index"
    )
    rescope_approvals: Mapped[list["RescopeApproval"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    msgchains: Mapped[list["MsgChain"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MsgChain.started_at",
    )


class WorkflowMessage(Base, UUIDMixin):
    __tablename__ = "workflow_messages"

    pentest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ambiguity_after: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    blockers_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usd_cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    session: Mapped[PentestSession] = relationship(back_populates="workflow_messages")


class RescopeApproval(Base, UUIDMixin):
    __tablename__ = "rescope_approvals"

    pentest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    discovered_targets: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requesting_step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    accepted_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rejected_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[PentestSession] = relationship(back_populates="rescope_approvals")


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
