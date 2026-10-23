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
