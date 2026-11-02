"""Weekly digests (docs/08, part 1; stage 6): one per restaurant and week, and one for the network.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "digests",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("input", postgresql.JSONB, nullable=False),
        sa.Column("output", postgresql.JSONB, nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("prompt_version", sa.Integer),
        sa.Column("built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source IN ('rules', 'model')", name="source_valid"),
    )
    # One digest a week per restaurant, and one for the network (no restaurant).
    op.execute(
        "CREATE UNIQUE INDEX ux_digests_week ON digests "
        "(tenant_id, coalesce(restaurant_id, '00000000-0000-0000-0000-000000000000'::uuid), week_start)"
    )
    rls.enable("digests", rls.restaurant_scope("restaurant_id"))


def downgrade() -> None:
    op.drop_table("digests")
