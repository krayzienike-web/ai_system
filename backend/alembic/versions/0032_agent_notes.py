"""Agents' messages (stage 9, ADR 0010): to the director of a restaurant or to the HQ, one per agent and
reason. Row-level security by restaurant; a note to the HQ is not seen by the restaurant's director.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
# As of this revision: a later migration that adds an agent changes the constraint itself.
AGENTS = ("inventory_prep", "task_due", "task_stuck", "data_check")
STATUSES = ("new", "accepted", "dismissed", "expired")


def upgrade() -> None:
    op.create_table(
        "agent_notes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column(
            "restaurant_id",
            UUID,
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("agent", sa.String(30), nullable=False),
        sa.Column("audience", sa.String(10), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("for_date", sa.Date, nullable=False),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE")),
        sa.Column("facts", postgresql.JSONB, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("items", postgresql.JSONB, nullable=False),
        sa.Column("proposal", postgresql.JSONB),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("prompt_version", sa.Integer),
        sa.Column("status", sa.String(10), nullable=False, server_default="new"),
        sa.Column("created_on", sa.Date, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("result_task_id", UUID, sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.CheckConstraint(f"agent IN {AGENTS}", name="agent_valid"),
        sa.CheckConstraint("audience IN ('director', 'hq')", name="audience_valid"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="status_valid"),
        sa.CheckConstraint("source IN ('rules', 'model')", name="source_valid"),
        sa.UniqueConstraint("tenant_id", "agent", "key"),
    )
    rls.enable("agent_notes", f"{rls.restaurant_scope()} AND (app.scope_all() OR audience = 'director')")


def downgrade() -> None:
    op.drop_table("agent_notes")
