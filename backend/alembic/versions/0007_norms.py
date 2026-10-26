"""Norms of the network (food-cost targets, loss allowances, write-off reasons) and classified write-offs.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "norm_settings",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("food_cost_target_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "food_cost_by_category", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("loss_default_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "loss_by_category", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "write_off_reasons", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("updated_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("food_cost_target_pct > 0 AND food_cost_target_pct < 100", name="food_cost_range"),
        sa.CheckConstraint("loss_default_pct >= 0 AND loss_default_pct < 100", name="loss_range"),
    )
    rls.enable("norm_settings", rls.tenant_scope())
    op.add_column(
        "write_offs", sa.Column("reason_code", sa.String(50), server_default="other", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("write_offs", "reason_code")
    op.drop_table("norm_settings")
