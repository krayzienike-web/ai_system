"""Directors read the network's KPIs and trend but must not write them (code review 27.10.2026).

A single policy for reads and writes let a director INSERT, UPDATE or DELETE the network-wide rows
(`restaurant_id IS NULL`) of `kpi_snapshots` and `trend_points`. Only the engine and HQ write them: reads keep
«own or network», writes need the tenant-wide scope. The run log: anyone of the network may ask for a run
or join the waiting one (an upload); only the tenant-wide scope (the engine, HQ) runs, finishes or deletes
one.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

from app.core import rls_migrations as rls

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWN_OR_NETWORK = (
    f"{rls.TENANT} AND (app.scope_all() OR restaurant_id IS NULL "
    "OR restaurant_id = ANY(app.current_restaurant_ids()))"
)
HQ_ONLY = f"{rls.TENANT} AND app.scope_all()"


def _split(table: str, read: str, insert: str, change: str, update: str | None = None) -> None:
    op.execute(f"DROP POLICY {table}_isolation ON {table}")
    op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT USING ({read})")
    op.execute(f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({insert})")
    up = update or change
    op.execute(f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({up}) WITH CHECK ({up})")
    op.execute(f"CREATE POLICY {table}_delete ON {table} FOR DELETE USING ({change})")


def _join(table: str, predicate: str) -> None:
    for name in ("read", "insert", "update", "delete"):
        op.execute(f"DROP POLICY {table}_{name} ON {table}")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})")


def upgrade() -> None:
    _split("kpi_snapshots", OWN_OR_NETWORK, HQ_ONLY, HQ_ONLY)
    _split("trend_points", OWN_OR_NETWORK, HQ_ONLY, HQ_ONLY)
    # An upload joins the waiting run (touches the queued row, keeping it queued); the rest is the engine's.
    joining = f"{rls.TENANT} AND (app.scope_all() OR status = 'queued')"
    _split("analytics_runs", rls.TENANT, rls.TENANT, HQ_ONLY, update=joining)


def downgrade() -> None:
    _join("analytics_runs", rls.TENANT)
    _join("trend_points", OWN_OR_NETWORK)
    _join("kpi_snapshots", OWN_OR_NETWORK)
