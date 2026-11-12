"""Units of an export per product (Q35): «упак», «бут» → the product's base unit, kept by the HQ for the
network. Row-level security by tenant.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "unit_factors",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("unit_text", sa.String(40), nullable=False),
        sa.Column("factor", sa.Numeric(14, 6), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "product_id", "unit", name="one_factor_per_unit"),
        sa.CheckConstraint("factor > 0", name="factor_positive"),
    )
    rls.enable("unit_factors", rls.tenant_scope())


def downgrade() -> None:
    op.drop_table("unit_factors")
