"""Flow Terminal + Tasks replay: persist terminal stdout + per-step order.

Revision ID: 013_flow_replay
Revises: 012_newflow_provider_mode
Create Date: 2026-07-19

Additive only. Backs the /flow Terminal + Tasks REPLAY-on-reload (they already
render LIVE off the WS `terminal` / `tasks` topics):
    - terminal_lines: one row per streamed adapter stdout line, ordered by a
      per-SESSION monotonic `seq`. The frontend replays this on reload and
      de-dupes the history/live boundary on `seq`.
    - agent_executions.step_order: the plan step order so the Tasks panel can
      overlay per-step status by order when the page reloads.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "013_flow_replay"
down_revision: Union[str, None] = "012_newflow_provider_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "terminal_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("agent_type", sa.String(length=100), nullable=True),
        sa.Column("line", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["pentest_sessions.id"],
            name="fk_terminal_lines_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["agent_executions.id"],
            name="fk_terminal_lines_execution_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_terminal_lines_session_seq",
        "terminal_lines",
        ["session_id", "seq"],
    )
    op.add_column(
        "agent_executions",
        sa.Column("step_order", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_executions", "step_order")
    op.drop_index("ix_terminal_lines_session_seq", table_name="terminal_lines")
    op.drop_table("terminal_lines")
