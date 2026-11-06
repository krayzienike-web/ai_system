"""Linked findings (stage 6.5, docs/12): findings with one cause carry the key and title of their story,
so the screens show them together and the money is not counted twice. Columns of the findings table: its
row-level security covers them.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("story_key", sa.String(200)))
    op.add_column("findings", sa.Column("story_title", sa.String(300)))
    op.create_index("ix_findings_tenant_story", "findings", ["tenant_id", "story_key"])


def downgrade() -> None:
    op.drop_index("ix_findings_tenant_story", table_name="findings")
    op.drop_column("findings", "story_title")
    op.drop_column("findings", "story_key")
