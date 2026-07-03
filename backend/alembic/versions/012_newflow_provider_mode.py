"""Add pentest_sessions new-flow provider/mode columns (PR1 — no behavior change).

Revision ID: 012_newflow_provider_mode
Revises: 011_oob_callbacks
Create Date: 2026-07-03

Additive only. Adds three columns consumed by the new-flow provider/mode UI:
    - model_map  (JSONB,  server_default '{}')          role -> model_id overrides
    - mode       (String(16), server_default 'automation')  "automation" | "assistant"
    - objective  (Text, nullable)                       Path-B operator objective

Existing rows backfill via the server defaults so the saved-workflow/no-LLM
demo lane (never entering `_run_autonomous_lane` per the service.py:315 gate)
reads byte-identical values. The provider preference reuses the existing
`llm_provider_pref` column — no new provider column is added (Finding 6).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "012_newflow_provider_mode"
down_revision: Union[str, None] = "011_oob_callbacks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "model_map",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column(
            "mode",
            sa.String(length=16),
            nullable=False,
            server_default="automation",
        ),
    )
    op.add_column(
        "pentest_sessions",
        sa.Column("objective", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pentest_sessions", "objective")
    op.drop_column("pentest_sessions", "mode")
    op.drop_column("pentest_sessions", "model_map")
