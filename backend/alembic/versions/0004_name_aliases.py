"""Name matching across systems: remembered aliases and batches waiting for a match.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TENANT = "tenant_id = app.current_tenant_id()"
OWN = "(app.scope_all() OR restaurant_id = ANY(app.current_restaurant_ids()))"


def upgrade() -> None:
    op.create_table(
        "name_aliases",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source_key", sa.String(300), nullable=False),
        sa.Column("source_text", sa.String(300), nullable=False),
        sa.Column("target_id", UUID, nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('product', 'menu_item', 'supplier')", name="kind_valid"),
    )
    # One match per name per scope (network-wide or one restaurant).
    op.execute(
        "CREATE UNIQUE INDEX uq_name_aliases_scope ON name_aliases "
        "(tenant_id, coalesce(restaurant_id, '00000000-0000-0000-0000-000000000000'::uuid), kind, source_key)"
    )
    # Everyone in the tenant reads network-wide matches and their own restaurant's; a director writes only
    # for their restaurant, HQ writes anything (USING for reads, WITH CHECK for writes).
    op.execute("ALTER TABLE name_aliases ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY name_aliases_isolation ON name_aliases "
        f"USING ({TENANT} AND (restaurant_id IS NULL OR {OWN})) "
        f"WITH CHECK ({TENANT} AND {OWN} AND (restaurant_id IS NOT NULL OR app.scope_all()))"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON name_aliases TO {get_settings().app_db_role}")

    op.add_column(
        "import_batches",
        sa.Column("unmatched", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.drop_constraint("ck_import_batches_status_valid", "import_batches")
    op.create_check_constraint(
        "status_valid",
        "import_batches",
        "status IN ('failed', 'needs_matching', 'validated', 'published', 'rolled_back')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_import_batches_status_valid", "import_batches")
    op.execute("DELETE FROM import_batches WHERE status = 'needs_matching'")
    op.create_check_constraint(
        "status_valid", "import_batches", "status IN ('failed', 'validated', 'published', 'rolled_back')"
    )
    op.drop_column("import_batches", "unmatched")
    op.drop_table("name_aliases")
