"""Source profiles by whom they serve (code review 02.11.2026, stage 5.5, pp. 5–6).

A director's confirmed marking changed how every restaurant's files and the HQ's reference files load. Now a
profile has a restaurant: a director's serves their restaurant, the HQ's (no restaurant) the whole network.
Everyone of the network reads the network's profiles and their own; only the tenant-wide scope writes a
network profile, a director only their restaurant's.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWN_OR_NETWORK = (
    f"{rls.TENANT} AND (app.scope_all() OR restaurant_id IS NULL "
    "OR restaurant_id = ANY(app.current_restaurant_ids()))"
)
OWN = f"{rls.TENANT} AND (app.scope_all() OR restaurant_id = ANY(app.current_restaurant_ids()))"


def upgrade() -> None:
    op.add_column(
        "source_profiles",
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
        ),
    )
    op.execute("DROP POLICY source_profiles_isolation ON source_profiles")
    op.execute(f"CREATE POLICY source_profiles_read ON source_profiles FOR SELECT USING ({OWN_OR_NETWORK})")
    op.execute(f"CREATE POLICY source_profiles_insert ON source_profiles FOR INSERT WITH CHECK ({OWN})")
    op.execute(
        f"CREATE POLICY source_profiles_update ON source_profiles FOR UPDATE USING ({OWN}) WITH CHECK ({OWN})"
    )
    op.execute(f"CREATE POLICY source_profiles_delete ON source_profiles FOR DELETE USING ({OWN})")


def downgrade() -> None:
    for name in ("read", "insert", "update", "delete"):
        op.execute(f"DROP POLICY source_profiles_{name} ON source_profiles")
    tenant = rls.TENANT
    op.execute(
        f"CREATE POLICY source_profiles_isolation ON source_profiles USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.drop_column("source_profiles", "restaurant_id")
