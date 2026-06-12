"""Create oob_callbacks table (PR8 / C5 — Interactsh OOB correlation).

Revision ID: 011_oob_callbacks
Revises: 010_xbow_w2_coordinator
Create Date: 2026-06-12

Additive only. The autonomous-lane OOB correlation persists one row per
canary-verified inbound callback.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_oob_callbacks"
down_revision: Union[str, None] = "010_xbow_w2_coordinator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oob_callbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pentest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pentest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "canary_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_oob_callbacks_pentest_session_id", "oob_callbacks", ["pentest_session_id"]
    )
    op.create_index(
        "ix_oob_callbacks_correlation_id", "oob_callbacks", ["correlation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_oob_callbacks_correlation_id", table_name="oob_callbacks")
    op.drop_index("ix_oob_callbacks_pentest_session_id", table_name="oob_callbacks")
    op.drop_table("oob_callbacks")
