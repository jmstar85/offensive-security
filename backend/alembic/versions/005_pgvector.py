"""Enable pgvector extension (v4.0 P1).

Revision ID: 005
Revises: 004
Create Date: 2026-05-16

This is a schema-only migration that enables the `vector` Postgres extension.
No tables are created here; `006_msgchains.py` creates `memory_entries` with
the `vector(384)` column type unlocked by this migration.

The extension is required for the hnsw index per ADR-002.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Guarded: only drop if no objects in the database depend on it. In
    # production rollback, the `006_msgchains` downgrade runs first and drops
    # the `memory_entries.embedding` column, so `vector` becomes safe to drop.
    op.execute("DROP EXTENSION IF EXISTS vector")
