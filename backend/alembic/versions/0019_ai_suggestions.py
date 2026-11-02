"""The assistant's proposals (ADR 0008, stage 5.5): hypotheses for a finding, a pre-check for the analyst,
ideas of new findings, the mapping of an unfamiliar file — each with what it was based on and a person's
decision; and the network's rules in words, which the assistant respects (`norm_settings.network_rules`).

A proposal about a restaurant is seen under that restaurant's row-level security (a director — their own);
about the network (no restaurant) — by the HQ only.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "ai_suggestions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject_id", UUID),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("basis", postgresql.JSONB, nullable=False),
        sa.Column("prompt", sa.String(60), nullable=False),
        sa.Column("prompt_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.Text),
        sa.CheckConstraint(
            "kind IN ('hypotheses', 'precheck', 'finding_idea', 'mapping')", name="kind_valid"
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'superseded')", name="status_valid"
        ),
    )
    op.create_index("ix_ai_suggestions_tenant_subject", "ai_suggestions", ["tenant_id", "kind", "subject_id"])
    rls.enable("ai_suggestions", rls.restaurant_scope("restaurant_id"))
    # The network's rules the assistant respects when it proposes steps («цены меняются с новым меню»).
    op.add_column(
        "norm_settings",
        sa.Column("network_rules", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("norm_settings", "network_rules")
    op.drop_table("ai_suggestions")
