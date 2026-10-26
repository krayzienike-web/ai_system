"""A network's own engine parameters (thresholds and windows of the detectors).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "norm_settings",
        sa.Column("engine_params", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("norm_settings", "engine_params")
