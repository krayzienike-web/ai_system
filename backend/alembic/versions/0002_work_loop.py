"""Work loop: findings, checks (experiments) and tasks with traceability to the measured result (ADR 0006).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
MONEY = sa.Numeric(14, 2)


def _id() -> sa.Column[UUID]:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _tenant_fk() -> sa.Column[UUID]:
    return sa.Column(
        "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _ts() -> sa.Column[sa.DateTime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "findings",
        _id(),
        _tenant_fk(),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("process", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("headline", sa.Text),
        sa.Column("effect_rub_month", MONEY),
        sa.Column("effect_note", sa.String(300)),
        sa.Column("actions", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(20), server_default="new", nullable=False),
        sa.Column("found_on", sa.Date, nullable=False),
        sa.Column("resolved_on", sa.Date),
        sa.Column("algorithm_version", sa.String(50), server_default="manual", nullable=False),
        _ts(),
        sa.CheckConstraint("kind IN ('problem', 'opportunity')", name="kind_valid"),
        sa.CheckConstraint(
            "status IN ('new', 'in_work', 'in_experiment', 'resolved', 'dismissed')", name="status_valid"
        ),
        sa.CheckConstraint("resolved_on IS NULL OR resolved_on >= found_on", name="resolved_after_found"),
    )
    op.create_table(
        "experiments",
        _id(),
        _tenant_fk(),
        sa.Column("finding_id", UUID, sa.ForeignKey("findings.id", ondelete="SET NULL"), index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("hypothesis", sa.Text, nullable=False),
        sa.Column("metric", sa.String(300), nullable=False),
        sa.Column("test_restaurant_ids", postgresql.ARRAY(UUID), nullable=False),
        sa.Column("control_restaurant_ids", postgresql.ARRAY(UUID), server_default="{}", nullable=False),
        sa.Column("starts_on", sa.Date, nullable=False),
        sa.Column("ends_on", sa.Date, nullable=False),
        sa.Column("expected_rub_month", MONEY, nullable=False),
        sa.Column("status", sa.String(20), server_default="proposed", nullable=False),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("verdict", sa.String(20)),
        sa.Column("effect_rub_month", MONEY),
        sa.Column("ci_low_rub_month", MONEY),
        sa.Column("ci_high_rub_month", MONEY),
        sa.Column("result_text", sa.Text),
        sa.Column("completed_on", sa.Date),
        _ts(),
        sa.CheckConstraint("status IN ('proposed', 'running', 'completed', 'rejected')", name="status_valid"),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('confirmed', 'inconclusive', 'rejected')", name="verdict_valid"
        ),
        sa.CheckConstraint("(status = 'completed') = (verdict IS NOT NULL)", name="verdict_when_completed"),
        sa.CheckConstraint("ends_on > starts_on", name="ends_after_start"),
        sa.CheckConstraint("cardinality(test_restaurant_ids) > 0", name="has_test_group"),
    )
    op.create_table(
        "tasks",
        _id(),
        _tenant_fk(),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", UUID, sa.ForeignKey("findings.id", ondelete="SET NULL"), index=True),
        sa.Column("experiment_id", UUID, sa.ForeignKey("experiments.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("checklist", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("assigned_by", sa.String(20), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_on", sa.Date, nullable=False),
        sa.Column("due_on", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), server_default="assigned", nullable=False),
        sa.Column("done_on", sa.Date),
        sa.Column("report", sa.Text),
        sa.Column("outcome_verdict", sa.String(20)),
        sa.Column("outcome_effect_rub_month", MONEY),
        sa.Column("outcome_text", sa.Text),
        sa.Column("outcome_measured_on", sa.Date),
        _ts(),
        sa.CheckConstraint("status IN ('assigned', 'in_progress', 'done')", name="status_valid"),
        sa.CheckConstraint("assigned_by IN ('hq', 'director')", name="assigned_by_valid"),
        sa.CheckConstraint(
            "outcome_verdict IS NULL OR outcome_verdict IN ('pending', 'confirmed', 'not_confirmed')",
            name="outcome_valid",
        ),
        sa.CheckConstraint("(status = 'done') = (done_on IS NOT NULL)", name="done_has_date"),
        sa.CheckConstraint("status = 'done' OR outcome_verdict IS NULL", name="outcome_only_when_done"),
        sa.CheckConstraint("due_on >= created_on", name="due_after_created"),
    )
    op.create_index("ix_tasks_restaurant_status", "tasks", ["restaurant_id", "status"])

    # A network-wide finding (restaurant_id IS NULL) falls outside every director's scope: HQ only.
    rls.enable("findings", rls.restaurant_scope())
    rls.enable("tasks", rls.restaurant_scope())
    # Checks are an HQ tool: a director follows a check through its tasks.
    rls.enable("experiments", f"{rls.tenant_scope()} AND app.scope_all()")


def downgrade() -> None:
    for table in ("tasks", "experiments", "findings"):
        op.drop_table(table)
