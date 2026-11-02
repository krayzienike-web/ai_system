"""Building and reading the weekly digests (docs/08, part 1; stage 6).

`publish` computes the input (`builder.build`, compared with the previous digest of the same scope),
writes the texts — by the model through `write` when given, by rules otherwise or when the model's text is
not usable — and keeps one digest per restaurant (or the network) and week: building again replaces it
(idempotent).

This module knows no model: the assistant passes `write` (app/ai/digest_writer.py), so the digests work,
and are tested, without it (import-linter: domain modules do not import `ai`).
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.digests import builder, texts
from app.digests.models import Digest
from app.tenancy.context import AccessContext, user_session
from app.tenancy.models import Restaurant

# The model's texts: (output, prompt version), or None to fall back to the rules.
Writer = Callable[[dict[str, Any]], tuple[dict[str, Any], int] | None]


def _scope(restaurant_id: UUID | None) -> Any:
    return Digest.restaurant_id.is_(None) if restaurant_id is None else Digest.restaurant_id == restaurant_id


def previous(session: Session, restaurant_id: UUID | None, week: builder.Week) -> Digest | None:
    return session.execute(
        select(Digest)
        .where(_scope(restaurant_id), Digest.week_start < week.start)
        .order_by(Digest.week_start.desc())
        .limit(1)
    ).scalar()


def publish(
    ctx: AccessContext,
    *,
    restaurant_id: UUID | None,
    week: builder.Week,
    today: date,
    write: Writer | None = None,
) -> UUID:
    """Builds and keeps the digest of one scope and week; returns its id. Three steps, so the model's minute
    holds no transaction: the input (a short transaction), the texts (outside), the row (another one)."""
    with user_session(ctx) as session:
        before = previous(session, restaurant_id, week)
        data = builder.build(
            session,
            restaurant_id=restaurant_id,
            week=week,
            today=today,
            previous=before.input if before else None,
        )
    written = write(data) if write is not None else None
    output, source, version = (
        (written[0], "model", written[1]) if written else (texts.by_rules(data), "rules", None)
    )
    with user_session(ctx) as session:
        digest = session.execute(
            select(Digest).where(_scope(restaurant_id), Digest.week_start == week.start).with_for_update()
        ).scalar()
        if digest is None:
            digest = Digest(
                tenant_id=ctx.tenant_id, restaurant_id=restaurant_id, week_start=week.start, week_end=week.end
            )
            session.add(digest)
        digest.input, digest.output, digest.source, digest.prompt_version = data, output, source, version
        digest.built_at = datetime.now(UTC)
        session.flush()
        return digest.id


def scopes(session: Session) -> list[UUID | None]:
    """What a network's weekly run builds: every restaurant the context sees, and the network (HQ only)."""
    ids: list[UUID | None] = list(session.execute(select(Restaurant.id).order_by(Restaurant.code)).scalars())
    return [*ids, None]


def latest(session: Session, restaurant_id: UUID | None, week_start: date | None = None) -> Digest:
    query = select(Digest).where(_scope(restaurant_id))
    if week_start is not None:
        query = query.where(Digest.week_start == week_start)
    digest = session.execute(query.order_by(Digest.week_start.desc()).limit(1)).scalar()
    if digest is None:  # none yet, or another restaurant's (row-level security): the same answer
        raise NotFoundError("Сводки пока нет")
    return digest


def weeks(session: Session, restaurant_id: UUID | None) -> list[tuple[date, date]]:
    """The archive: weeks with a digest, the latest first."""
    rows = session.execute(
        select(Digest.week_start, Digest.week_end)
        .where(_scope(restaurant_id))
        .order_by(Digest.week_start.desc())
    ).all()
    return [(a, b) for a, b in rows]
