"""The assistant's log of model calls (`ai_runs`, docs/03-architecture.md; ADR 0005).

Each call: who asked, the task, the prompt and its version, the model, the request and the reply, tokens,
cost and time. A person sees their own calls, the HQ the network's. The application may only add and read
rows: the log is also what the daily request budget counts.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls
from app.core.config import get_settings

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("prompt", sa.String(60), nullable=False),
        sa.Column("prompt_version", sa.Integer, nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stop_reason", sa.String(30)),
        sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("response", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'refused', 'truncated', 'failed')", name="status_valid"),
    )
    op.create_index("ix_ai_runs_tenant_user_created", "ai_runs", ["tenant_id", "user_id", "created_at"])
    rls.enable("ai_runs", rls.own_user_scope("user_id"))
    op.execute(f"REVOKE UPDATE, DELETE ON ai_runs FROM {get_settings().app_db_role}")


def downgrade() -> None:
    op.drop_table("ai_runs")
