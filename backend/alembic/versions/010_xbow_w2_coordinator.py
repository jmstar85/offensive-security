"""Add coordinator columns to pentest_sessions and create agent_family_instances table.

Revision ID: 010_xbow_w2_coordinator
Revises: 009_user_llm_credentials
Create Date: 2026-05-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_xbow_w2_coordinator"
down_revision: Union[str, None] = "009_user_llm_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pentest_sessions",
        sa.Column("understanding_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("plan_of_work_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("coordinator_revision_no", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("llm_provider_pref", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "agent_family_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("pentest_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_kind", sa.String(32), nullable=False),
        sa.Column("parent_family_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_depth", sa.Integer(), server_default="3", nullable=False),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["pentest_session_id"],
            ["pentest_sessions.id"],
            name="fk_agent_family_instances_pentest_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_family_id"],
            ["agent_family_instances.id"],
            name="fk_agent_family_instances_parent_family_id",
        ),
    )
    op.create_index(
        "ix_agent_family_instances_pentest_session_id",
        "agent_family_instances",
        ["pentest_session_id"],
    )
    op.create_index(
        "ix_agent_family_instances_status",
        "agent_family_instances",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_family_instances_status", table_name="agent_family_instances")
    op.drop_index("ix_agent_family_instances_pentest_session_id", table_name="agent_family_instances")
    op.drop_table("agent_family_instances")
    op.drop_column("pentest_sessions", "llm_provider_pref")
    op.drop_column("pentest_sessions", "coordinator_revision_no")
    op.drop_column("pentest_sessions", "plan_of_work_json")
    op.drop_column("pentest_sessions", "understanding_json")
