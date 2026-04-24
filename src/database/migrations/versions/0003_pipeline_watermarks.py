"""pipeline watermarks table for incremental extraction

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-24 00:02:00

Creates the watermark registry used by PostgresExtractor (and any future
incremental extractor) to track the last successfully-processed point
per pipeline, enabling idempotent re-runs.

Design notes:
    - One row per pipeline_name (natural PK).
    - watermark is TIMESTAMPTZ because most upstream systems use timestamps,
      but we also persist a free-form `watermark_value_text` for non-temporal
      watermarks (e.g., monotonic integer IDs, cursors).
    - run_metadata JSONB captures run-specific context (rows processed,
      source system, Prefect run_id) for audit trails.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_watermarks",
        sa.Column("pipeline_name", sa.Text, primary_key=True),
        sa.Column(
            "watermark",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("watermark_value_text", sa.Text),
        sa.Column("run_metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Trigger to keep updated_at in sync without relying on the app
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_touch_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$;
    """)

    op.execute("""
        CREATE TRIGGER watermarks_touch_updated_at
        BEFORE UPDATE ON pipeline_watermarks
        FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS watermarks_touch_updated_at ON pipeline_watermarks")
    op.execute("DROP FUNCTION IF EXISTS trg_touch_updated_at()")
    op.drop_table("pipeline_watermarks")
