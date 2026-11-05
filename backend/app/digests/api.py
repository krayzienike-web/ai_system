"""The weekly digests on the screens (docs/08 part 1, stage 6): the latest or a given week, the archive.

Everything shown is computed by the code (`input`); the texts (`output`) are the model's or the rules'. A
director reads their restaurant's digests; the network's and other restaurants' answer 404 (row-level
security). Building again — the assistant's API (`POST /digests/rebuild`), as the model writes the texts.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.digests import builder, reactions, service, texts
from app.digests.models import Digest
from app.insights.models import Finding
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["digests"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class DigestItemOut(BaseModel):
    finding_id: UUID
    title: str
    process: str
    effect_per_month: str | None
    text: str  # the model's or the rules'
    causes: list[str]
    actions: list[str]
    taken: bool  # a task on it: «Беру в работу» was pressed (or the HQ assigned one)
    disagreed: str | None  # the reader's «Не согласен»: its reason
    disagreed_comment: str | None  # and its comment, so changing the reason keeps it
    effect_rub_month: Decimal | None  # for the task dialog's «если сработает, эффект — до …»


class DigestProcessOut(BaseModel):
    process: str
    title: str
    status: str
    index: int
    change: int | None
    losses_per_month: str | None
    open_problems: int


class DigestKpisOut(BaseModel):
    food_cost_actual: str | None
    food_cost_theory: str | None
    write_offs_share_of_revenue: str | None
    food_cost_period: str | None
    revenue: str | None


class OnTableOut(BaseModel):
    losses: str | None
    potential: str | None
    total: str | None


class ImprovedOut(BaseModel):
    tasks_done: int
    tasks: list[str]
    confirmed_effect_per_month: str | None
    processes_better: list[str]


class DigestOut(BaseModel):
    id: UUID
    scope: str  # restaurant | network
    restaurant_id: UUID | None
    restaurant: str | None  # «R01 · Name»
    week_start: date
    week_end: date
    week: str
    source: str  # model | rules
    built_at: datetime
    headline: str
    kpis: DigestKpisOut | None
    kpis_previous_digest: DigestKpisOut | None
    network_average: DigestKpisOut | None
    processes: list[DigestProcessOut]
    problems: list[DigestItemOut]
    opportunities: list[DigestItemOut]
    risks: list[DigestItemOut]
    on_table: OnTableOut
    improved: ImprovedOut
    last_count: str | None
    restaurants_count: int | None


class DigestWeekOut(BaseModel):
    week_start: date
    week_end: date


def _items(items: list[dict[str, Any]], texts: dict[str, str], now: reactions.Live) -> list[DigestItemOut]:
    return [
        DigestItemOut(
            finding_id=i["finding_id"],
            title=i["title"],
            process=i["process"],
            effect_per_month=i["effect_per_month"],
            text=texts.get(i["finding_id"]) or i["title"],
            causes=i["causes"],
            actions=i["actions"],
            taken=i["taken"] or UUID(i["finding_id"]) in now.taken,
            disagreed=(now.mine.get(UUID(i["finding_id"])) or (None, None))[0],
            disagreed_comment=(now.mine.get(UUID(i["finding_id"])) or (None, None))[1],
            effect_rub_month=i.get("effect_rub_month"),
        )
        for i in items
    ]


def _as_director_sees(
    session: Session, data: dict[str, Any], out: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A digest stored before ADR 0009 may hold findings the director does not see yet: read through the
    findings' row-level security, they are left out — with the totals and «Главное» they made (review
    05.11.2026, p. 2; test pass). A digest built since holds none, and is shown as it is."""
    kinds = ("problems", "opportunities", "risks")
    stored = [i["finding_id"] for k in kinds for i in data[k]]
    seen = {str(f) for f in session.execute(select(Finding.id).where(Finding.id.in_(stored))).scalars()}
    if seen == set(stored):
        return data, out
    data = {**data, **{k: [i for i in data[k] if i["finding_id"] in seen] for k in kinds}}

    def total(kind: str) -> Decimal:
        return sum(
            (Decimal(i["effect_rub_month"] or 0) for i in data[kind] if "effect_rub_month" in i), Decimal(0)
        )

    losses, potential = total("problems"), total("opportunities")
    data["on_table"] = {
        "losses": builder.money(losses),
        "potential": builder.money(potential),
        "total": builder.money(losses + potential),
    }
    return data, {**out, "headline": texts.headline(data)}


def digest_out(session: Session, ctx: AccessContext, d: Digest) -> DigestOut:
    data, out = d.input, d.output
    if not ctx.role.is_hq:
        data, out = _as_director_sees(session, data, out)
    ids = [UUID(i["finding_id"]) for i in data["problems"] + data["opportunities"] + data["risks"]]
    now = reactions.live(session, ctx, ids, d.restaurant_id)
    place = data.get("restaurant")
    texts = out.get("items") or {}
    return DigestOut(
        id=d.id,
        scope=data["scope"],
        restaurant_id=d.restaurant_id,
        restaurant=f"{place['code']} · {place['name']}" if place else None,
        week_start=d.week_start,
        week_end=d.week_end,
        week=data["week"],
        source=d.source,
        built_at=d.built_at,
        headline=out["headline"],
        kpis=data["kpis"],
        kpis_previous_digest=data["kpis_previous_digest"],
        # Never the network's revenue (its sum, not an average), also in digests stored before the fix.
        network_average={**data["network_average"], "revenue": None} if data["network_average"] else None,
        processes=data["processes"],
        problems=_items(data["problems"], texts, now),
        opportunities=_items(data["opportunities"], texts, now),
        risks=_items(data["risks"], texts, now),
        on_table=data["on_table"],
        improved=data["improved"],
        last_count=data["last_count"],
        restaurants_count=data["restaurants_count"],
    )


def scope_of(ctx: AccessContext, restaurant_id: UUID | None) -> UUID | None:
    """A director's digest is their restaurant's even when none is named; the network's is the HQ's."""
    return restaurant_id if restaurant_id is not None or ctx.role.is_hq else ctx.restaurant_id


@router.get("/digests/latest", response_model=DigestOut)
def latest(
    ctx: CanRead,
    session: SessionDep,
    restaurant_id: UUID | None = None,
    week_start: Annotated[date | None, Query()] = None,
) -> DigestOut:
    """The latest digest (or of `week_start`) of the restaurant, or of the network without one (HQ)."""
    return digest_out(session, ctx, service.latest(session, scope_of(ctx, restaurant_id), week_start))


@router.get("/digests/weeks", response_model=list[DigestWeekOut])
def weeks(ctx: CanRead, session: SessionDep, restaurant_id: UUID | None = None) -> list[DigestWeekOut]:
    """The archive: weeks with a digest, the latest first."""
    return [
        DigestWeekOut(week_start=a, week_end=b)
        for a, b in service.weeks(session, scope_of(ctx, restaurant_id))
    ]


class DisagreeIn(BaseModel):
    reason: Literal["wrong_data", "explained", "already_fixed", "other"]
    comment: str | None = Field(default=None, max_length=1000)
    digest_id: UUID | None = None


class DisagreementOut(BaseModel):
    id: UUID
    finding_id: UUID
    finding_title: str
    restaurant: str
    reason: str
    reason_title: str
    comment: str | None
    created_at: datetime


class ReasonOut(BaseModel):
    reason: str
    title: str


@router.get("/digests/disagree-reasons", response_model=list[ReasonOut])
def disagree_reasons(ctx: CanRead) -> list[ReasonOut]:
    """The form's choices, named by the server."""
    return [ReasonOut(reason=k, title=v) for k, v in reactions.REASON_TITLE.items()]


@router.post("/findings/{finding_id}/disagree", status_code=204)
def disagree(finding_id: UUID, body: DisagreeIn, ctx: CanRead, session: SessionDep, today: TodayDep) -> None:
    """«Не согласен» — a director's reason, for the HQ; again replaces it."""
    reactions.disagree(
        session,
        ctx,
        finding_id,
        reason=body.reason,
        comment=body.comment,
        digest_id=body.digest_id,
        today=today,
    )
    session.commit()


@router.delete("/findings/{finding_id}/disagree", status_code=204)
def withdraw(finding_id: UUID, ctx: CanRead, session: SessionDep) -> None:
    reactions.withdraw(session, ctx, finding_id)
    session.commit()


@router.get("/digests/disagreements", response_model=list[DisagreementOut])
def disagreements(
    ctx: CanRead, session: SessionDep, restaurant_id: UUID | None = None
) -> list[DisagreementOut]:
    """The HQ's list of directors' disagreements, the latest first; of one restaurant when given."""
    return [DisagreementOut(**r.__dict__) for r in reactions.for_hq(session, ctx, restaurant_id)]
