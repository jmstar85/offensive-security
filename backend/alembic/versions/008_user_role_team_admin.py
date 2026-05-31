"""Add team_admin value to users.role CHECK constraint.

Revision ID: 008
Revises: 007
Create Date: 2026-05-31

Widens the users.role CHECK constraint to allow the new 'team_admin' role,
which permits raw_conversation WebSocket subscriptions without full admin
privileges.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('user','admin','team_admin','member'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('user','admin','member'))"
    )
