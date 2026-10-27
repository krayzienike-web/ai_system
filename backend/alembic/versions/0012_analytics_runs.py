"""Recalculation after every upload: a log of the engine's runs (queued, running, done, failed), so a second
upload while a run waits does not queue another, and the screens can say when the findings were updated.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "analytics_runs",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("trigger", sa.String(20), nullable=False),  # upload | manual
        sa.Column("status", sa.String(20), nullable=False),  # queued | running | done | failed
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created", sa.Integer),
        sa.Column("updated", sa.Integer),
        sa.Column("removed", sa.Integer),
        sa.Column("error", sa.Text),
        sa.CheckConstraint("trigger IN ('upload', 'manual')", name="trigger_valid"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="status_valid"),
    )
    # At most one waiting run per network: later uploads join it.
    op.create_index(
        "ux_analytics_runs_queued",
        "analytics_runs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
    )
    # Every role of the network may see when its findings were last updated (no figures in here).
    rls.enable("analytics_runs", rls.TENANT)


def downgrade() -> None:
    op.drop_table("analytics_runs")
