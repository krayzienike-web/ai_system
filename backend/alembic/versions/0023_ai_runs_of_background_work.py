"""The networks' background work of stage 6 (the weekly digests):
- its calls to the model are logged too: no person behind them (`user_id` empty), read only by the
  background work itself, never by a person;
- the scheduler learns which networks there are (`app.tenant_ids()`: the ids only — the tenants table is
  under row-level security, each network sees only itself).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

from app.core import rls_migrations as rls
from app.core.config import get_settings

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTHOR_ONLY = f"{rls.TENANT} AND user_id = app.current_user_id()"
SYSTEM = "'00000000-0000-0000-0000-000000000000'::uuid"  # app.tenancy.context.SYSTEM_USER
AUTHOR_OR_SYSTEM = (
    f"{rls.TENANT} AND (user_id = app.current_user_id()"
    f" OR (user_id IS NULL AND app.current_user_id() = {SYSTEM}))"
)


def _policy(predicate: str) -> None:
    op.execute("DROP POLICY ai_runs_isolation ON ai_runs")
    op.execute(f"CREATE POLICY ai_runs_isolation ON ai_runs USING ({predicate}) WITH CHECK ({predicate})")


def upgrade() -> None:
    _policy(AUTHOR_OR_SYSTEM)
    op.execute(
        """
        CREATE FUNCTION app.tenant_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS
        $$ SELECT id FROM public.tenants ORDER BY id $$;
        REVOKE ALL ON FUNCTION app.tenant_ids() FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app.tenant_ids() TO {get_settings().app_db_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.tenant_ids()")
    op.execute("DELETE FROM ai_runs WHERE user_id IS NULL")
    _policy(AUTHOR_ONLY)
