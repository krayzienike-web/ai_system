"""Engine findings: stable key, module, confidence, period, evidence; manual review before directors.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("key", sa.String(200)))
    op.add_column("findings", sa.Column("module", sa.String(10)))
    op.add_column("findings", sa.Column("confidence", sa.String(10)))
    op.add_column("findings", sa.Column("period_from", sa.Date))
    op.add_column("findings", sa.Column("period_to", sa.Date))
    op.add_column("findings", sa.Column("evidence", postgresql.JSONB))
    op.create_index(
        "ux_findings_tenant_key",
        "findings",
        ["tenant_id", "key"],
        unique=True,
        postgresql_where=sa.text("key IS NOT NULL"),
    )
    op.create_check_constraint(
        "confidence_valid", "findings", "confidence IS NULL OR confidence IN ('high', 'medium', 'low')"
    )
    # Manual review: an engine finding waits for HQ to check it against the data (null: made by hand).
    op.add_column("findings", sa.Column("review_status", sa.String(20)))
    op.add_column("findings", sa.Column("review_reason", sa.String(30)))
    op.add_column("findings", sa.Column("review_note", sa.Text))
    op.add_column(
        "findings", sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"))
    )
    op.add_column("findings", sa.Column("reviewed_on", sa.Date))
    op.create_check_constraint(
        "review_status_valid",
        "findings",
        "review_status IS NULL OR review_status IN ('pending', 'confirmed', 'rejected')",
    )
    op.add_column(
        "norm_settings", sa.Column("review_findings", sa.Boolean, server_default=sa.true(), nullable=False)
    )
    # A director sees a finding of their restaurant only after HQ has confirmed it.
    op.execute("DROP POLICY findings_isolation ON findings")
    checked = "app.scope_all() OR review_status IS NULL OR review_status = 'confirmed'"
    visible = f"{rls.restaurant_scope()} AND ({checked})"
    op.execute(f"CREATE POLICY findings_isolation ON findings USING ({visible}) WITH CHECK ({visible})")


def downgrade() -> None:
    op.execute("DROP POLICY findings_isolation ON findings")
    scope = rls.restaurant_scope()
    op.execute(f"CREATE POLICY findings_isolation ON findings USING ({scope}) WITH CHECK ({scope})")
    op.drop_column("norm_settings", "review_findings")
    op.drop_constraint("ck_findings_review_status_valid", "findings")
    for col in ("reviewed_on", "reviewed_by", "review_note", "review_reason", "review_status"):
        op.drop_column("findings", col)
    op.drop_constraint("ck_findings_confidence_valid", "findings")
    op.drop_index("ux_findings_tenant_key", "findings")
    for col in ("evidence", "period_to", "period_from", "confidence", "module", "key"):
        op.drop_column("findings", col)
