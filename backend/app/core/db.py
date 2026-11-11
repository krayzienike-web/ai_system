"""Database engine, sessions and the row-level security context.

Every request runs in one transaction. Before any query the access context is written into
transaction-local settings (`app.tenant_id`, `app.user_id`, `app.scope_all`, `app.restaurant_ids`),
which the RLS policies read. Settings are transaction-local, so pooled connections never leak context.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@dataclass(frozen=True)
class RlsContext:
    tenant_id: UUID
    user_id: UUID
    scope_all: bool
    restaurant_ids: frozenset[UUID] = field(default_factory=frozenset)


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def apply_rls_context(session: Session, ctx: RlsContext) -> None:
    session.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant_id, true),"
            " set_config('app.user_id', :user_id, true),"
            " set_config('app.scope_all', :scope_all, true),"
            " set_config('app.restaurant_ids', :restaurant_ids, true)"
        ),
        {
            "tenant_id": str(ctx.tenant_id),
            "user_id": str(ctx.user_id),
            "scope_all": "on" if ctx.scope_all else "off",
            "restaurant_ids": ",".join(sorted(str(r) for r in ctx.restaurant_ids)),
        },
    )


@contextmanager
def transaction() -> Iterator[Session]:
    """A session in an open transaction without any RLS context (sees nothing protected)."""
    with get_sessionmaker()() as session, session.begin():
        yield session


def role_problems(session: Session) -> list[str]:
    """Why row-level security would not hold for the connection the API runs on (pre-pilot review 10.11.2026,
    p. 21). Policies do not apply to a superuser, a role with BYPASSRLS or a table's owner, so the API refuses
    to start as one: `FORCE ROW LEVEL SECURITY` would also stop the schema owner, which seeds and migrates."""
    problems: list[str] = []
    role = session.execute(
        text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    if role.rolsuper:
        problems.append(f"{role.rolname} is a superuser")
    if role.rolbypassrls:
        problems.append(f"{role.rolname} has BYPASSRLS")
    owned = session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user")
    ).scalars()
    problems.extend(f"{role.rolname} owns {t}" for t in owned)
    unprotected = session.execute(
        text(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity "
            "AND relname <> 'alembic_version' ORDER BY relname"
        )
    ).scalars()
    problems.extend(f"{t} has no row-level security" for t in unprotected)
    return problems
