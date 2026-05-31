"""Create user_llm_credentials table for at-rest encrypted LLM provider credentials.

Revision ID: 009
Revises: 008
Create Date: 2026-05-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_llm_credentials",
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
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("credential_type", sa.String(32), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_llm_credentials_user_id"),
        sa.UniqueConstraint("user_id", "provider", "label", name="uq_user_provider_label"),
    )
    op.create_index("idx_user_llm_credentials_user_id", "user_llm_credentials", ["user_id"])
    op.create_index(
        "idx_user_llm_credentials_provider_revoked",
        "user_llm_credentials",
        ["provider", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_llm_credentials_provider_revoked", table_name="user_llm_credentials")
    op.drop_index("idx_user_llm_credentials_user_id", table_name="user_llm_credentials")
    op.drop_table("user_llm_credentials")
