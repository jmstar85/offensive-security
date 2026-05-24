"""Add msgchains and memory_entries tables (v4.0 P1).

Revision ID: 006
Revises: 005
Create Date: 2026-05-16

Creates:
- `msgchains` — per-role conversation transcript (one row per role-chain per session).
- `memory_entries` — pgvector-backed memory store seeded from `app/knowledge/*.yaml`.
- hnsw index on `memory_entries.embedding` per ADR-002 (m=16, ef_construction=64,
  vector_cosine_ops).

Note: this migration assumes `005_pgvector.py` has already enabled the `vector`
extension. The hnsw index is created with the table; pgvector's hnsw is
in-memory and rebuilt on insert, so creating the index before seeding is fine.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- msgchains -------------------------------------------------------
    op.create_table(
        "msgchains",
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
        sa.Column("role_name", sa.String(32), nullable=False),
        sa.Column(
            "messages_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("retries", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_msgchains_session_started",
        "msgchains",
        ["pentest_session_id", "started_at"],
    )
    op.create_index("ix_msgchains_role_name", "msgchains", ["role_name"])

    # --- memory_entries (pgvector) ---------------------------------------
    # Use raw SQL for the `embedding vector(384)` column type because alembic's
    # autogenerate doesn't know about pgvector types. The Vector type is
    # registered with SQLAlchemy via `pgvector.sqlalchemy.Vector` in the model.
    op.execute(
        """
        CREATE TABLE memory_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            domain_tag VARCHAR(32) NOT NULL,
            source_yaml_path TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            embedding vector(384) NOT NULL,
            metadata_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index(
        "ix_memory_entries_domain_tag", "memory_entries", ["domain_tag"]
    )

    # hnsw index per ADR-002: m=16 ef_construction=64 with cosine distance.
    op.execute(
        """
        CREATE INDEX memory_entries_embedding_hnsw_idx
        ON memory_entries
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_entries_embedding_hnsw_idx")
    op.drop_index("ix_memory_entries_domain_tag", table_name="memory_entries")
    op.execute("DROP TABLE IF EXISTS memory_entries")

    op.drop_index("ix_msgchains_role_name", table_name="msgchains")
    op.drop_index("ix_msgchains_session_started", table_name="msgchains")
    op.drop_table("msgchains")
