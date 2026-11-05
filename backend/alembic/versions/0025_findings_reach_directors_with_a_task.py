"""A finding reaches a director only through the HQ's decision (ADR 0009, stage 6.1): a director sees a
finding of their restaurant once it passed the review and the HQ put a task on the restaurant for it. Before
that it is the HQ's alone — on every screen, in the digest and in the chat's tools: all read through this.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

from app.core import rls_migrations as rls

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKED = "review_status IS NULL OR review_status = 'confirmed'"
# Read under the same person's row-level security: a director sees the tasks of their restaurant.
TASKED = (
    "EXISTS (SELECT 1 FROM tasks t"
    " WHERE t.finding_id = findings.id AND t.restaurant_id = findings.restaurant_id)"
)


def _policy(visible: str) -> None:
    op.execute("DROP POLICY findings_isolation ON findings")
    op.execute(f"CREATE POLICY findings_isolation ON findings USING ({visible}) WITH CHECK ({visible})")


def upgrade() -> None:
    op.create_index("ix_tasks_finding_restaurant", "tasks", ["finding_id", "restaurant_id"])  # read per row
    _policy(f"{rls.restaurant_scope()} AND (app.scope_all() OR (({CHECKED}) AND {TASKED}))")


def downgrade() -> None:
    _policy(f"{rls.restaurant_scope()} AND (app.scope_all() OR {CHECKED})")
    op.drop_index("ix_tasks_finding_restaurant", "tasks")
