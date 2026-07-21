import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    # Per-session tier approval flags (e.g. approved_active_recon,
    # approved_active_exploit). Consumed by filter_by_tier_flags in the
    # orchestrator safety chain. Empty dict means no tier gates are open —
    # any step whose tier requires a flag will be blocked.
    approval_flags: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    cost_usd_accum: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("0"), nullable=False
    )
    paused_for_rescope_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rescope_request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    understanding_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan_of_work_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    coordinator_revision_no: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    llm_provider_pref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # --- New-flow provider/mode schema (migration 012) -----------------------
    # Per-role model overrides (role -> model_id). Empty dict ⇒ the session
    # default (model_id) applies to every role. Catalog-validation of values is
    # deferred to PR4's ModelSelector.
    model_map: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    # Session execution mode: "automation" (autonomous lane) | "assistant"
    # (operator-driven chat). Set at create; never mutated.
    mode: Mapped[str] = mapped_column(
        String(16), default="automation", server_default="automation", nullable=False
    )
    # Path-B operator objective persisted so approve/launcher can pass it as the
    # execution prompt. Distinct from `prompt` (the nullable=False draft seed).
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Mirror migration 003's constraint on the MODEL so the schema is enforced in
    # tests (SQLite builds from metadata, not migrations) and the send_message
    # duplicate-turn 409 guard is exercised the same way it is in Postgres.
    __table_args__ = (
        UniqueConstraint(
            "pentest_session_id", "turn_index", "role",
            name="uq_workflow_messages_session_turn_role",
        ),
    )

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
    # --- Flow-replay schema (migration 013) ----------------------------------
    # Plan step order, so the Tasks panel can overlay per-step status by order
    # when the /flow page reloads (the live stream carries it in the event).
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[PentestSession] = relationship(back_populates="executions")


class TerminalLine(Base, UUIDMixin):
    """One streamed adapter stdout line, persisted so the /flow Terminal panel
    REPLAYS on reload (migration 013). The panel already renders LIVE off the WS
    ``terminal`` topic; these rows are the reload/replay source.

    ``seq`` is a per-SESSION monotonic ordinal assigned by ``TerminalLineSink``
    (seeded from ``max(seq)`` in the DB). The SAME ``seq`` is published at the top
    level of the live ``log`` event, so the frontend de-dupes the history/live
    boundary on it. ``execution_id`` is nullable + ``ON DELETE SET NULL`` so a
    line survives its execution row being pruned.
    """

    __tablename__ = "terminal_lines"
    __table_args__ = (
        Index("ix_terminal_lines_session_seq", "session_id", "seq"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    line: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttackScenario(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "attack_scenarios"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pentest_sessions.id"), nullable=False
    )
    steps_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_assessment: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    session: Mapped[PentestSession] = relationship(back_populates="scenarios")
