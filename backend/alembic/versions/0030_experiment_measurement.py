"""What a check measures and how (stage 7, docs/05 «Замер»): the design, the metric and its object, the
products of the «items» control, the period before the check, the smallest visible effect, the last
measurement. Columns of the experiments table: its row-level security covers them.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "experiments", sa.Column("design", sa.String(20), nullable=False, server_default="restaurants")
    )
    op.create_check_constraint(
        "design_valid", "experiments", "design IN ('restaurants', 'items', 'before_after')"
    )
    op.add_column("experiments", sa.Column("metric_kind", sa.String(20)))
    op.create_check_constraint(
        "metric_kind_valid",
        "experiments",
        "metric_kind IS NULL OR metric_kind IN ('overuse', 'writeoffs', 'price', 'discounts', 'voids')",
    )
    op.add_column(
        "experiments",
        sa.Column("metric_product_id", UUID, sa.ForeignKey("products.id", ondelete="SET NULL")),
    )
    op.add_column("experiments", sa.Column("metric_cashier", sa.String(100)))
    op.add_column(
        "experiments",
        sa.Column("control_product_ids", postgresql.ARRAY(UUID), nullable=False, server_default="{}"),
    )
    op.add_column("experiments", sa.Column("baseline_from", sa.Date))
    op.add_column("experiments", sa.Column("baseline_to", sa.Date))
    op.add_column("experiments", sa.Column("mde_rub_month", sa.Numeric(14, 2)))
    op.add_column("experiments", sa.Column("measured_on", sa.Date))


def downgrade() -> None:
    for column in (
        "measured_on",
        "mde_rub_month",
        "baseline_to",
        "baseline_from",
        "control_product_ids",
        "metric_cashier",
        "metric_product_id",
    ):
        op.drop_column("experiments", column)
    op.drop_constraint(op.f("ck_experiments_metric_kind_valid"), "experiments", type_="check")
    op.drop_column("experiments", "metric_kind")
    op.drop_constraint(op.f("ck_experiments_design_valid"), "experiments", type_="check")
    op.drop_column("experiments", "design")
