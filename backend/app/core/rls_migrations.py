"""Helpers for row-level security in migrations.

Conventions:
- `tenant`      — rows visible when tenant_id matches the request's tenant.
- `restaurant`  — additionally limited to the caller's restaurants unless the caller has tenant-wide scope.
- `own_user`    — users without tenant-wide scope see only rows tied to themselves (column `user_col`).
Every policy applies to reads (USING) and writes (WITH CHECK).
"""

from alembic import op

from app.core.config import get_settings

TENANT = "tenant_id = app.current_tenant_id()"


def _app_role() -> str:
    return get_settings().app_db_role


def enable(table: str, predicate: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_app_role()}")


def tenant_scope() -> str:
    return TENANT


def restaurant_scope(column: str = "restaurant_id") -> str:
    return f"{TENANT} AND (app.scope_all() OR {column} = ANY(app.current_restaurant_ids()))"


def own_user_scope(user_col: str = "user_id") -> str:
    return f"{TENANT} AND (app.scope_all() OR {user_col} = app.current_user_id())"
