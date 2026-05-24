"""Phase 0 — Workflow draft schema (additive on pentest_sessions) + workflow_messages + rescope_approvals

Revision ID: 003
Revises: 002
Create Date: 2026-05-14

Implements §1.1 of plan v3.2.1:
- Additive columns on pentest_sessions (no separate workflows table)
- Extended status CHECK enum
- New workflow_messages table (chat-turn log)
- New rescope_approvals table (paused_for_rescope audit, resolves Critic D-1 BLOCKER)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PENTEST_SESSION_STATUSES = (
    # legacy
    "pending",
    "running",
    "completed",
    "failed",
    "killed",
    # added in 003
    "draft",
    "interviewing",
    "interview_paused",
    "ready_for_review",
    "needs_human_review",
    "approved",
    "executing",
    "paused_for_rescope",
    "rejected",
)

INTERVIEW_STATES = (
    "not_started",
    "interviewing",
    "ready_for_review",
    "needs_human_review",
    "interview_paused",
)

RESCOPE_STATUSES = ("pending", "approved", "rejected", "timed_out")


def upgrade() -> None:
    # --- pentest_sessions additive columns --------------------------------
    op.add_column(
        "pentest_sessions",
        sa.Column("domain_agent_slug", sa.String(64), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "model_id",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'claude-sonnet-4-6'"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "draft_plan_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "interview_state",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'not_started'"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "interview_turn_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "ambiguity_score",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("1.000"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("ambiguity_override_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "ambiguity_override_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("ambiguity_override_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "approved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "cost_usd_accum",
            sa.Numeric(8, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("paused_for_rescope_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("rescope_request_json", JSONB(), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("resume_token", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id"),
            nullable=True,
        ),
    )

    # CHECK constraints for enum membership
    statuses = ", ".join(f"'{s}'" for s in PENTEST_SESSION_STATUSES)
    op.create_check_constraint(
        "ck_pentest_sessions_status",
        "pentest_sessions",
        f"status IN ({statuses})",
    )
    interview = ", ".join(f"'{s}'" for s in INTERVIEW_STATES)
    op.create_check_constraint(
        "ck_pentest_sessions_interview_state",
        "pentest_sessions",
        f"interview_state IN ({interview})",
    )
    op.create_check_constraint(
        "ck_pentest_sessions_interview_turn_count_nonneg",
        "pentest_sessions",
        "interview_turn_count >= 0",
    )
    op.create_check_constraint(
        "ck_pentest_sessions_ambiguity_range",
        "pentest_sessions",
        "ambiguity_score >= 0 AND ambiguity_score <= 1",
    )

    # --- workflow_messages -------------------------------------------------
    op.create_table(
        "workflow_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pentest_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("ambiguity_after", sa.Numeric(4, 3), nullable=True),
        sa.Column("blockers_json", JSONB(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("usd_cost", sa.Numeric(8, 5), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "pentest_session_id",
            "turn_index",
            "role",
            name="uq_workflow_messages_session_turn_role",
        ),
        sa.CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_workflow_messages_role",
        ),
    )
    op.create_index(
        "ix_workflow_messages_session",
        "workflow_messages",
        ["pentest_session_id"],
    )

    # --- rescope_approvals -------------------------------------------------
    op.create_table(
        "rescope_approvals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pentest_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("discovered_targets", JSONB(), nullable=False),
        sa.Column("requesting_step_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("accepted_targets", JSONB(), nullable=True),
        sa.Column("rejected_targets", JSONB(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status = 'pending' OR decided_at IS NOT NULL",
            name="ck_rescope_decided_when_terminal",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'timed_out')",
            name="ck_rescope_status",
        ),
    )
    op.create_index(
        "ix_rescope_session_status",
        "rescope_approvals",
        ["pentest_session_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_rescope_session_status", table_name="rescope_approvals")
    op.drop_table("rescope_approvals")
    op.drop_index("ix_workflow_messages_session", table_name="workflow_messages")
    op.drop_table("workflow_messages")

    for ck in (
        "ck_pentest_sessions_ambiguity_range",
        "ck_pentest_sessions_interview_turn_count_nonneg",
        "ck_pentest_sessions_interview_state",
        "ck_pentest_sessions_status",
    ):
        op.drop_constraint(ck, "pentest_sessions", type_="check")

    for col in (
        "team_id",
        "resume_token",
        "rescope_request_json",
        "paused_for_rescope_at",
        "cost_usd_accum",
        "approved_by",
        "approved_at",
        "ambiguity_override_reason",
        "ambiguity_override_by",
        "ambiguity_override_at",
        "ambiguity_score",
        "interview_turn_count",
        "interview_state",
        "draft_plan_json",
        "model_id",
        "domain_agent_slug",
    ):
        op.drop_column("pentest_sessions", col)
