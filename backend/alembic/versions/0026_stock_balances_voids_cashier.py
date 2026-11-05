"""Exports the stage 6.5 findings need (docs/09): «Остатки на дату» (iiko) — the books' stock at the end of a
day; «Удаления и отмены» (r_keeper) — dishes removed from checks and checks cancelled, by cashier, before or
after printing; the cashier of a sale. Facts of a restaurant: its row-level security, like the other facts.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(14, 4)
MONEY = sa.Numeric(14, 2)


def _fact(name: str, *columns: sa.Column, check: sa.CheckConstraint) -> None:  # type: ignore[type-arg]
    op.create_table(
        name,
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
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
        check,
    )
    op.create_index(f"ix_{name}_restaurant_day", name, ["restaurant_id", "day"])
    op.create_index(f"ix_{name}_tenant_day", name, ["tenant_id", "day"])
    rls.enable(name, rls.restaurant_scope())


def upgrade() -> None:
    _fact(
        "stock_balances",
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        check=sa.CheckConstraint("qty >= 0", name="qty_nonnegative"),
    )
    _fact(
        "voids",
        sa.Column("check_no", sa.String(100)),
        sa.Column("menu_item_id", UUID, sa.ForeignKey("menu_items.id", ondelete="RESTRICT")),
        sa.Column("qty", QTY, nullable=False, server_default="1"),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("cashier", sa.String(100)),
        sa.Column("after_print", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(200)),
        check=sa.CheckConstraint("amount >= 0", name="amount_nonnegative"),
    )
    op.add_column("sales", sa.Column("cashier", sa.String(100)))


def downgrade() -> None:
    op.drop_column("sales", "cashier")
    op.drop_table("voids")
    op.drop_table("stock_balances")
