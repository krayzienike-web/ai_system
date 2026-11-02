"""The weekly digests on the screens (docs/08 part 1, stage 6): the latest or a given week, the archive.

Everything shown is computed by the code (`input`); the texts (`output`) are the model's or the rules'. A
director reads their restaurant's digests; the network's and other restaurants' answer 404 (row-level
security). Building again — the assistant's API (`POST /digests/rebuild`), as the model writes the texts.
"""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import SessionDep, require
from app.digests import service
from app.digests.models import Digest
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
    taken: bool


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


def _items(items: list[dict[str, Any]], texts: dict[str, str]) -> list[DigestItemOut]:
    return [
        DigestItemOut(
            finding_id=i["finding_id"],
            title=i["title"],
            process=i["process"],
            effect_per_month=i["effect_per_month"],
            text=texts.get(i["finding_id"]) or i["title"],
            causes=i["causes"],
            actions=i["actions"],
            taken=i["taken"],
        )
        for i in items
    ]


def digest_out(d: Digest) -> DigestOut:
    data, out = d.input, d.output
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
        network_average=data["network_average"],
        processes=data["processes"],
        problems=_items(data["problems"], texts),
        opportunities=_items(data["opportunities"], texts),
        risks=_items(data["risks"], texts),
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
    return digest_out(service.latest(session, scope_of(ctx, restaurant_id), week_start))


@router.get("/digests/weeks", response_model=list[DigestWeekOut])
def weeks(ctx: CanRead, session: SessionDep, restaurant_id: UUID | None = None) -> list[DigestWeekOut]:
    """The archive: weeks with a digest, the latest first."""
    return [
        DigestWeekOut(week_start=a, week_end=b)
        for a, b in service.weeks(session, scope_of(ctx, restaurant_id))
    ]
