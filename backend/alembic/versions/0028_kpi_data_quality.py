"""The data quality score of a restaurant, 0–100 (stage 6.5, docs/12), and what lowered it: stored with the
KPI snapshot of the engine's run, under the snapshot's row-level security.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kpi_snapshots", sa.Column("data_quality", sa.Integer))
    op.add_column("kpi_snapshots", sa.Column("data_quality_parts", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("kpi_snapshots", "data_quality_parts")
    op.drop_column("kpi_snapshots", "data_quality")
