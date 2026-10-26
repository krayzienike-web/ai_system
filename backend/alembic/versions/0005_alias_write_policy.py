"""Name aliases: separate read and write policies; remember which aliases a published file used.

A single policy FOR ALL let a director UPDATE or DELETE a network-wide alias, because USING (which governs
the rows UPDATE/DELETE may touch) includes network rows for reading. Reads and writes are now split.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "tenant_id = app.current_tenant_id()"
OWN = "(app.scope_all() OR restaurant_id = ANY(app.current_restaurant_ids()))"
READ = f"{TENANT} AND (restaurant_id IS NULL OR {OWN})"
WRITE = f"{TENANT} AND {OWN} AND (restaurant_id IS NOT NULL OR app.scope_all())"


def upgrade() -> None:
    op.execute("DROP POLICY name_aliases_isolation ON name_aliases")
    op.execute(f"CREATE POLICY name_aliases_read ON name_aliases FOR SELECT USING ({READ})")
    op.execute(f"CREATE POLICY name_aliases_insert ON name_aliases FOR INSERT WITH CHECK ({WRITE})")
    op.execute(
        f"CREATE POLICY name_aliases_update ON name_aliases FOR UPDATE USING ({WRITE}) WITH CHECK ({WRITE})"
    )
    op.execute(f"CREATE POLICY name_aliases_delete ON name_aliases FOR DELETE USING ({WRITE})")
    # "kind:source_key" of every alias a published file relied on: when a match turns out wrong,
    # the files built on it are listed and can be re-processed.
    op.add_column(
        "import_batches",
        sa.Column("aliases_used", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("import_batches", "aliases_used")
    for name in ("read", "insert", "update", "delete"):
        op.execute(f"DROP POLICY name_aliases_{name} ON name_aliases")
    op.execute(
        f"CREATE POLICY name_aliases_isolation ON name_aliases USING ({READ}) "
        f"WITH CHECK ({TENANT} AND {OWN} AND (restaurant_id IS NOT NULL OR app.scope_all()))"
    )
