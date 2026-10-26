"""Backend owns the screens' logic (ADR 0007): how a finding is shown, task checklists and reminders,
check details and rollout, KPI snapshots and the weekly trend written by the engine run (a director sees
their own and the network's).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    # How a finding is shown: summary, causes, metric, scale, composition, chart, documents (docs/12).
    op.add_column("findings", sa.Column("view", JSONB))

    op.add_column(
        "tasks",
        sa.Column("checklist_done", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("tasks", sa.Column("reminded_on", sa.Date))

    op.add_column("experiments", sa.Column("baseline", sa.Text))
    op.add_column("experiments", sa.Column("progress_text", sa.Text))  # written by the measurement
    op.add_column("experiments", sa.Column("rollout_rub_month", sa.Numeric(14, 2)))  # by the measurement
    op.add_column("experiments", sa.Column("rollout_on", sa.Date))
    op.add_column(
        "experiments", sa.Column("proposed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"))
    )

    op.create_table(
        "kpi_snapshots",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        # NULL: the network as a whole (revenue-weighted), visible to every role of the tenant.
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("computed_on", sa.Date, nullable=False),
        sa.Column("food_cost_from", sa.Date),
        sa.Column("food_cost_to", sa.Date),
        sa.Column("revenue", sa.Numeric(16, 2), nullable=False),
        sa.Column("food_cost_actual", sa.Numeric(8, 6)),
        sa.Column("food_cost_theory", sa.Numeric(8, 6)),
        sa.Column("write_offs_from", sa.Date),
        sa.Column("write_offs_to", sa.Date),
        sa.Column("write_offs_share", sa.Numeric(8, 6)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ux_kpi_snapshots_restaurant",
        "kpi_snapshots",
        ["tenant_id", sa.text("coalesce(restaurant_id, '00000000-0000-0000-0000-000000000000'::uuid)")],
        unique=True,
    )
    own_or_network = (
        f"{rls.TENANT} AND (app.scope_all() OR restaurant_id IS NULL "
        "OR restaurant_id = ANY(app.current_restaurant_ids()))"
    )
    rls.enable("kpi_snapshots", own_or_network)

    # «Найденный потенциал» at the end of each week (losses + missed profit of checked open findings) and the
    # confirmed effect so far: the trend lines and «к прошлой неделе». NULL restaurant: the network.
    op.create_table(
        "trend_points",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("losses", sa.Numeric(14, 2), nullable=False),
        sa.Column("potential", sa.Numeric(14, 2), nullable=False),
        sa.Column("open_findings", sa.Integer, nullable=False),
        sa.Column("returned", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ux_trend_points_week",
        "trend_points",
        [
            "tenant_id",
            sa.text("coalesce(restaurant_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "week_end",
        ],
        unique=True,
    )
    rls.enable("trend_points", own_or_network)


def downgrade() -> None:
    op.drop_table("trend_points")
    op.drop_table("kpi_snapshots")
    for column in ("proposed_by", "rollout_on", "rollout_rub_month", "progress_text", "baseline"):
        op.drop_column("experiments", column)
    op.drop_column("tasks", "reminded_on")
    op.drop_column("tasks", "checklist_done")
    op.drop_column("findings", "view")
