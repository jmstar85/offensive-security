"""RBAC: add is_active column and role CHECK constraint

Revision ID: 002
Revises: 001
Create Date: 2026-04-13
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_active column with default True
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # Add CHECK constraint to restrict role values
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('admin', 'member')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "is_active")
