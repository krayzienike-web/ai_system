"""Directors' «Не согласен» with a finding (docs/08 part 1; stage 6): reason and comment, read by the HQ.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "disagreements",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", UUID, sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest_id", UUID, sa.ForeignKey("digests.id", ondelete="SET NULL")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('wrong_data', 'explained', 'already_fixed', 'other')", name="reason_valid"
        ),
        sa.UniqueConstraint("finding_id", "user_id"),
    )
    rls.enable("disagreements", rls.restaurant_scope("restaurant_id"))


def downgrade() -> None:
    op.drop_table("disagreements")
