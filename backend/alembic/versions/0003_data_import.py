"""Data import: network reference data (catalog), restaurant facts and import batches.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(14, 4)
MONEY = sa.Numeric(14, 2)


def _id() -> sa.Column[UUID]:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _tenant_fk() -> sa.Column[UUID]:
    return sa.Column(
        "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _ts() -> sa.Column[sa.DateTime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _fact(name: str, *columns: sa.Column, checks: Sequence[sa.CheckConstraint] = ()) -> None:  # type: ignore[type-arg]
    op.create_table(
        name,
        _id(),
        _tenant_fk(),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "import_batch_id",
            UUID,
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day", sa.Date, nullable=False),
        *columns,
        *checks,
    )
    op.create_index(f"ix_{name}_restaurant_day", name, ["restaurant_id", "day"])


def upgrade() -> None:
    op.create_table(
        "products",
        _id(),
        _tenant_fk(),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("base_unit", sa.String(10), nullable=False),
        sa.Column("shelf_life_days", sa.Integer),
        _ts(),
        sa.UniqueConstraint("tenant_id", "code"),
        sa.CheckConstraint("base_unit IN ('kg', 'l', 'pcs')", name="base_unit_valid"),
    )
    op.create_table(
        "suppliers",
        _id(),
        _tenant_fk(),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("inn", sa.String(12)),
        _ts(),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_table(
        "menu_items",
        _id(),
        _tenant_fk(),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("price", MONEY),
        _ts(),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_table(
        "recipe_lines",
        _id(),
        _tenant_fk(),
        sa.Column(
            "menu_item_id",
            UUID,
            sa.ForeignKey("menu_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("gross_qty", QTY, nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        _ts(),
        sa.UniqueConstraint("menu_item_id", "product_id", "valid_from"),
        sa.CheckConstraint("gross_qty > 0", name="gross_positive"),
    )
    op.create_table(
        "import_batches",
        _id(),
        _tenant_fk(),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("template", sa.String(50), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("raw", sa.LargeBinary, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_valid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("period_from", sa.Date),
        sa.Column("period_to", sa.Date),
        sa.Column("errors", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("warnings", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("column_map", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        _ts(),
        sa.CheckConstraint(
            "status IN ('failed', 'validated', 'published', 'rolled_back')", name="status_valid"
        ),
    )
    op.create_index("ix_import_batches_tenant_sha", "import_batches", ["tenant_id", "sha256"])

    _fact(
        "sales",
        sa.Column("menu_item_id", UUID, sa.ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("revenue", MONEY, nullable=False),
        sa.Column("discount", MONEY, nullable=False, server_default="0"),
        checks=[sa.CheckConstraint("qty >= 0", name="qty_nonnegative")],
    )
    _fact(
        "receipts",
        sa.Column("doc_no", sa.String(100)),
        sa.Column("supplier_id", UUID, sa.ForeignKey("suppliers.id", ondelete="RESTRICT")),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("vat", MONEY),
        checks=[sa.CheckConstraint("qty > 0", name="qty_positive")],
    )
    _fact(
        "write_offs",
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("reason", sa.String(200)),
        checks=[sa.CheckConstraint("qty > 0", name="qty_positive")],
    )
    _fact(
        "inventory_counts",
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("book_qty", QTY),
        sa.Column("actual_qty", QTY, nullable=False),
        checks=[sa.CheckConstraint("actual_qty >= 0", name="actual_nonnegative")],
    )

    # Reference data is shared by the tenant (writing it is an HQ permission, checked in the API).
    for table in ("products", "suppliers", "menu_items", "recipe_lines"):
        rls.enable(table, rls.tenant_scope())
    # Facts and batches belong to a restaurant; a reference-data batch (no restaurant) is HQ only.
    for table in ("import_batches", "sales", "receipts", "write_offs", "inventory_counts"):
        rls.enable(table, rls.restaurant_scope())


def downgrade() -> None:
    for table in (
        "inventory_counts",
        "write_offs",
        "receipts",
        "sales",
        "import_batches",
        "recipe_lines",
        "menu_items",
        "suppliers",
        "products",
    ):
        op.drop_table(table)
