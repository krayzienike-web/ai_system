"""Source profiles (docs/09, «Адаптивный импорт»; stage 5.5): the mapping of an unfamiliar export's columns
onto a template, confirmed by a person once and applied to later files with the same headers. Network-wide,
like the catalog: every role of the network that uploads files uses them; only people who upload may add them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "source_profiles",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("template", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("mapping", postgresql.JSONB, nullable=False),
        sa.Column("confirmed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_source_profiles_tenant_template", "source_profiles", ["tenant_id", "template"])
    rls.enable("source_profiles", rls.TENANT)


def downgrade() -> None:
    op.drop_table("source_profiles")
