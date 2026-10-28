"""The model-call log holds whole conversations, so it is as private as they are (code review 28.10.2026,
stage 5, p. 5): only the author reads their calls — the HQ too sees only its own. The cost of a model without
a price is left empty instead of 0.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

from app.core import rls_migrations as rls

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTHOR_ONLY = f"{rls.TENANT} AND user_id = app.current_user_id()"


def upgrade() -> None:
    op.execute("DROP POLICY ai_runs_isolation ON ai_runs")
    op.execute(f"CREATE POLICY ai_runs_isolation ON ai_runs USING ({AUTHOR_ONLY}) WITH CHECK ({AUTHOR_ONLY})")
    op.alter_column("ai_runs", "cost_usd", nullable=True, server_default=None)


def downgrade() -> None:
    op.execute("UPDATE ai_runs SET cost_usd = 0 WHERE cost_usd IS NULL")
    op.alter_column("ai_runs", "cost_usd", nullable=False, server_default="0")
    predicate = rls.own_user_scope("user_id")
    op.execute("DROP POLICY ai_runs_isolation ON ai_runs")
    op.execute(f"CREATE POLICY ai_runs_isolation ON ai_runs USING ({predicate}) WITH CHECK ({predicate})")
