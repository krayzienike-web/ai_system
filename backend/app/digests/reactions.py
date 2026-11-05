"""A director's reactions to the digest's items (docs/08 part 1, stage 6).

- «Беру в работу» — removed (ADR 0009): a director's digest holds only findings with the HQ's task, shown
  live as `taken`.
- «Не согласен» — with a reason, for the HQ (`Disagreement`): stored here.
- «Обсудить с ИИ» — the chat with the finding (`POST /chat`, `finding_id`): nothing to store.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, InvalidError, NotFoundError
from app.digests.models import Digest, Disagreement
from app.insights.models import Finding
from app.insights.visible import visible_finding
from app.tasks.models import Task
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

REASON_TITLE = {
    "wrong_data": "Данные неверны",
    "explained": "Есть объяснение (праздник, разовое событие)",
    "already_fixed": "Уже исправлено",
    "other": "Другое",
}


def _director(ctx: AccessContext) -> UUID:
    if not ctx.can(Permission.TASKS_EXECUTE) or ctx.restaurant_id is None:
        raise ForbiddenError("«Не согласен» — для директора ресторана")
    return ctx.restaurant_id


def disagree(
    session: Session,
    ctx: AccessContext,
    finding_id: UUID,
    *,
    reason: str,
    comment: str | None,
    digest_id: UUID | None,
    today: date,
) -> Disagreement:
    restaurant_id = _director(ctx)
    visible_finding(session, ctx, finding_id, today=today)  # another restaurant's or unreviewed: 404
    if reason not in REASON_TITLE:
        raise InvalidError("Неизвестная причина")
    comment = (comment or "").strip() or None
    if reason == "other" and comment is None:
        raise InvalidError("Напишите, с чем не согласны")
    if digest_id is not None:
        digest = session.get(Digest, digest_id)
        named = (
            {i["finding_id"] for k in ("problems", "opportunities", "risks") for i in digest.input[k]}
            if digest
            else set()
        )
        if str(finding_id) not in named:  # the digest the reaction came from must hold the item
            raise NotFoundError("Сводка не найдена")
    # Saying it again replaces it; two clicks at once do not fail on the unique (finding, person) pair.
    stmt = insert(Disagreement).values(
        tenant_id=ctx.tenant_id,
        restaurant_id=restaurant_id,
        finding_id=finding_id,
        user_id=ctx.user_id,
        digest_id=digest_id,
        reason=reason,
        comment=comment,
        created_at=datetime.now(UTC),
    )
    row_id = session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Disagreement.finding_id, Disagreement.user_id],
            set_={k: stmt.excluded[k] for k in ("reason", "comment", "digest_id", "created_at")},
        ).returning(Disagreement.id)
    ).scalar_one()
    session.flush()
    row = session.get(Disagreement, row_id, populate_existing=True)
    assert row is not None
    return row


def withdraw(session: Session, ctx: AccessContext, finding_id: UUID) -> None:
    _director(ctx)
    row = session.execute(
        select(Disagreement).where(Disagreement.finding_id == finding_id, Disagreement.user_id == ctx.user_id)
    ).scalar()
    if row is None:
        raise NotFoundError("Вы не отмечали несогласие с этим пунктом")
    session.delete(row)
    session.flush()


@dataclass(frozen=True)
class Live:
    """What changed since the digest was built: tasks taken and the reader's own disagreements."""

    taken: frozenset[UUID]
    mine: dict[UUID, tuple[str, str | None]]  # finding → the reader's reason and comment


def live(session: Session, ctx: AccessContext, finding_ids: list[UUID], restaurant_id: UUID | None) -> Live:
    tasks = select(Task.finding_id).distinct().where(Task.finding_id.in_(finding_ids))
    if restaurant_id is not None:
        tasks = tasks.where(Task.restaurant_id == restaurant_id)
    taken = frozenset(f for f in session.execute(tasks).scalars() if f is not None)
    mine = {
        f: (reason, comment)
        for f, reason, comment in session.execute(
            select(Disagreement.finding_id, Disagreement.reason, Disagreement.comment).where(
                Disagreement.finding_id.in_(finding_ids), Disagreement.user_id == ctx.user_id
            )
        ).all()
    }
    return Live(taken, mine)


@dataclass(frozen=True)
class DisagreementRow:
    id: UUID
    finding_id: UUID
    finding_title: str
    restaurant: str
    reason: str
    reason_title: str
    comment: str | None
    created_at: datetime


def for_hq(session: Session, ctx: AccessContext, restaurant_id: UUID | None = None) -> list[DisagreementRow]:
    """The HQ's list, the latest first; of one restaurant when given (its digest's page)."""
    if not ctx.can(Permission.NETWORK_COMPARE):
        raise ForbiddenError("Несогласия директоров видит управляющая компания")
    rows = session.execute(
        select(Disagreement, Finding.title, Restaurant.code, Restaurant.name)
        .join(Finding, Finding.id == Disagreement.finding_id)
        .join(Restaurant, Restaurant.id == Disagreement.restaurant_id)
        .where(true() if restaurant_id is None else Disagreement.restaurant_id == restaurant_id)
        .order_by(Disagreement.created_at.desc())
    ).all()
    return [
        DisagreementRow(
            id=d.id,
            finding_id=d.finding_id,
            finding_title=title,
            restaurant=f"{code} · {name}",
            reason=d.reason,
            reason_title=REASON_TITLE[d.reason],
            comment=d.comment,
            created_at=d.created_at,
        )
        for d, title, code, name in rows
    ]
