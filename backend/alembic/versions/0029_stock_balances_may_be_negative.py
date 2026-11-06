"""«Остатки на дату» is the books' stock: it goes below zero when a document is missing (M7 catches that). A
negative line must not block the whole file (code review of stage 6.5, p. 5).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_stock_balances_qty_nonnegative"), "stock_balances", type_="check")


def downgrade() -> None:
    op.execute("UPDATE stock_balances SET qty = 0 WHERE qty < 0")
    op.create_check_constraint("qty_nonnegative", "stock_balances", "qty >= 0")
