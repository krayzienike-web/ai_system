"""Semi-finished products in recipes and transfers between restaurants.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TENANT = "tenant_id = app.current_tenant_id()"
MINE = "restaurant_id = ANY(app.current_restaurant_ids())"
INCOMING = "to_restaurant_id = ANY(app.current_restaurant_ids())"


def upgrade() -> None:
    op.add_column("products", sa.Column("is_semi", sa.Boolean, server_default=sa.false(), nullable=False))
    op.add_column(
        "recipe_lines",
        sa.Column("semi_product_id", UUID, sa.ForeignKey("products.id", ondelete="CASCADE"), index=True),
    )
    op.alter_column("recipe_lines", "menu_item_id", nullable=True)
    op.drop_constraint("uq_recipe_lines_menu_item_id", "recipe_lines")
    op.create_check_constraint(
        "one_parent", "recipe_lines", "(menu_item_id IS NULL) <> (semi_product_id IS NULL)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_recipe_lines_version ON recipe_lines "
        "(coalesce(menu_item_id, semi_product_id), product_id, valid_from)"
    )

    op.create_table(
        "transfers",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "to_restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "import_batch_id",
            UUID,
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", sa.Numeric(14, 4), nullable=False),
        sa.CheckConstraint("qty > 0", name="qty_positive"),
        sa.CheckConstraint("to_restaurant_id <> restaurant_id", name="not_to_itself"),
    )
    op.create_index("ix_transfers_restaurant_day", "transfers", ["restaurant_id", "day"])
    op.create_index("ix_transfers_to_day", "transfers", ["to_restaurant_id", "day"])
    # The sender writes; both the sender and the receiver read (the receiver needs incoming goods).
    op.execute("ALTER TABLE transfers ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY transfers_read ON transfers FOR SELECT "
        f"USING ({TENANT} AND (app.scope_all() OR {MINE} OR {INCOMING}))"
    )
    write = f"{TENANT} AND (app.scope_all() OR {MINE})"
    op.execute(f"CREATE POLICY transfers_insert ON transfers FOR INSERT WITH CHECK ({write})")
    op.execute(f"CREATE POLICY transfers_update ON transfers FOR UPDATE USING ({write}) WITH CHECK ({write})")
    op.execute(f"CREATE POLICY transfers_delete ON transfers FOR DELETE USING ({write})")
    app_role = get_settings().app_db_role
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON transfers TO {app_role}")

    # A transfer names the other restaurant, which a director cannot see (RLS). This resolves one exact
    # code or name inside the caller's tenant to an id — nothing else about other restaurants is revealed.
    op.execute(
        """
        CREATE FUNCTION app.resolve_restaurant(p_text text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS
        $$ SELECT r.id FROM public.restaurants r
           WHERE r.tenant_id = app.current_tenant_id()
             AND (r.code = btrim(p_text) OR lower(r.name) = lower(btrim(p_text)))
           LIMIT 1 $$;
        REVOKE ALL ON FUNCTION app.resolve_restaurant(text) FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app.resolve_restaurant(text) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.resolve_restaurant(text)")
    op.drop_table("transfers")
    op.execute("DROP INDEX uq_recipe_lines_version")
    op.drop_constraint("ck_recipe_lines_one_parent", "recipe_lines")
    op.execute("DELETE FROM recipe_lines WHERE menu_item_id IS NULL")
    op.alter_column("recipe_lines", "menu_item_id", nullable=False)
    op.create_unique_constraint(
        "uq_recipe_lines_menu_item_id", "recipe_lines", ["menu_item_id", "product_id", "valid_from"]
    )
    op.drop_column("recipe_lines", "semi_product_id")
    op.drop_column("products", "is_semi")
