"""The weekly run (Q24: Monday 08:30 Moscow time, about the previous Monday–Sunday): every network, every
restaurant and the network itself. Background work — the system's context, no person behind it.

`writer_for` gives the model's texts writer for the run's context (the worker passes the assistant's, when
the model is on); a digest that fails is logged and the others are built.
"""

import logging
from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.digests import builder, service
from app.tenancy.context import AccessContext, system_context

log = logging.getLogger(__name__)

WriterFor = Callable[[AccessContext], service.Writer | None]


def tenants() -> list[UUID]:
    with get_sessionmaker()() as session:
        return list(session.execute(text("SELECT app.tenant_ids()")).scalars())


def run(
    tenant_id: UUID, today: date, writer_for: WriterFor | None = None, *, only_missing: bool = False
) -> int:
    """Builds the network's digests of the week before `today`; returns how many were built. `only_missing`:
    the catch-up runs of the Monday morning build only what is not there yet (code review 03.11.2026,
    p. 17)."""
    week = builder.Week.before(today)
    with get_sessionmaker()() as session:
        ctx = system_context(session, tenant_id)
        scopes = service.scopes(session)
        if only_missing:
            scopes = [s for s in scopes if not service.exists(session, s, week)]
    write = writer_for(ctx) if writer_for is not None else None
    built = 0
    for restaurant_id in scopes:
        try:
            service.publish(ctx, restaurant_id=restaurant_id, week=week, today=today, write=write)
            built += 1
        except Exception:
            log.exception("digest of %s (restaurant %s) for %s failed", tenant_id, restaurant_id, week.start)
    return built
