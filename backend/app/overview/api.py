"""Overview screens (ADR 0007): figures, rankings and conclusions come from `service`; the screens draw."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import SessionDep, require
from app.core.period import PeriodDep, TodayDep
from app.insights.api import FindingOut, findings_out
from app.insights.service import FindingWork
from app.overview import service
from app.tasks.api import TaskOut, tasks_out
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["overview"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]
CanCompare = Annotated[AccessContext, Depends(require(Permission.NETWORK_COMPARE))]


class ContextOut(BaseModel):
    today: date
    data_until: date | None
    next_count_on: date | None


class TrendOut(BaseModel):
    labels: list[str]
    week_ends: list[date]
    on_table: list[Decimal]
    returned: list[Decimal]
    open_findings: list[int]


class RankOut(BaseModel):
    restaurant_id: UUID
    code: str
    name: str
    losses: Decimal
    delta: Decimal | None
    top_problem: str | None


class CommonOut(BaseModel):
    key: str
    process: str
    title: str
    where: str
    losses: Decimal | None
    note: str
    finding_id: UUID | None


class NetworkOut(BaseModel):
    restaurants: int
    losses: Decimal
    potential: Decimal
    found_count: int
    confirmed: Decimal
    completed_checks: int
    checks_waiting: int
    overdue_tasks: int
    trend: TrendOut
    ranking: list[RankOut]
    common: list[CommonOut]


class ProcessOut(BaseModel):
    process: str
    title: str
    losses: Decimal
    findings: list[FindingOut]


class KpiOut(BaseModel):
    food_cost_actual: Decimal | None
    food_cost_theory: Decimal | None
    write_offs_share: Decimal | None
    food_cost_from: date | None
    food_cost_to: date | None


class RestaurantRef(BaseModel):
    id: UUID
    code: str
    name: str
    city: str | None


class WeekOut(BaseModel):
    restaurant: RestaurantRef
    losses: Decimal
    potential: Decimal
    found_count: int
    delta_week: Decimal | None
    digest: str
    digest_findings: list[FindingOut]
    actions: list[FindingOut]
    top: list[FindingOut]
    processes: list[ProcessOut]
    fine_processes: list[str]
    kpi: KpiOut | None
    network_kpi: KpiOut | None
    kpi_answer: str | None
    stock_risks: list[dict[str, str]]  # M6 is not built yet: always empty
    done_tasks: list[TaskOut]
    results_answer: str


class RestaurantRowOut(BaseModel):
    id: UUID
    code: str
    name: str
    city: str | None
    losses: Decimal
    potential: Decimal
    delta: Decimal | None
    food_cost: Decimal | None
    late: int
    tasks_done: int
    tasks_total: int
    bad_processes: int
    stale_data: str | None


class BadgesOut(BaseModel):
    inbox: int
    open_tasks: int


@router.get("/overview/context")
def get_context(ctx: CanRead, session: SessionDep, today: TodayDep) -> ContextOut:
    c = service.context(session, today)
    return ContextOut(today=c.today, data_until=c.data_until, next_count_on=c.next_count_on)


@router.get("/overview/network")
def get_network(ctx: CanCompare, session: SessionDep, period: PeriodDep, today: TodayDep) -> NetworkOut:
    n = service.network(session, period, today)
    return NetworkOut(
        restaurants=n.restaurants,
        losses=n.losses,
        potential=n.potential,
        found_count=n.found_count,
        confirmed=n.confirmed,
        completed_checks=n.completed_checks,
        checks_waiting=n.checks_waiting,
        overdue_tasks=n.overdue_tasks,
        trend=TrendOut(**n.trend.__dict__),
        ranking=[RankOut(**r.__dict__) for r in n.ranking],
        common=[CommonOut(**c.__dict__) for c in n.common],
    )


@router.get("/overview/restaurants")
def get_restaurants(ctx: CanCompare, session: SessionDep, today: TodayDep) -> list[RestaurantRowOut]:
    return [RestaurantRowOut(**r.__dict__) for r in service.restaurants(session, today)]


@router.get("/overview/restaurants/{code}")
def get_restaurant(code: str, ctx: CanRead, session: SessionDep, today: TodayDep) -> WeekOut:
    w = service.restaurant(session, code, today)

    def out(items: list[FindingWork]) -> list[FindingOut]:
        return findings_out(session, ctx, items)

    def kpi(k: service.Kpis | None) -> KpiOut | None:
        return KpiOut(**k.__dict__) if k else None

    r = w.restaurant
    return WeekOut(
        restaurant=RestaurantRef(id=r.id, code=r.code, name=r.name, city=r.city),
        losses=w.losses,
        potential=w.potential,
        found_count=w.found_count,
        delta_week=w.delta_week,
        digest=w.digest,
        digest_findings=out(w.digest_findings),
        actions=out(w.actions),
        top=out(w.top),
        processes=[
            ProcessOut(process=p.process, title=p.title, losses=p.losses, findings=out(p.findings))
            for p in w.processes
        ],
        fine_processes=w.fine_processes,
        kpi=kpi(w.kpi),
        network_kpi=kpi(w.network_kpi),
        kpi_answer=w.kpi_answer,
        stock_risks=[],
        done_tasks=tasks_out(session, w.done_tasks, today),
        results_answer=w.results_answer,
    )


@router.get("/overview/badges")
def get_badges(ctx: CanRead, session: SessionDep, today: TodayDep) -> BadgesOut:
    return BadgesOut(**service.badges(session, today, hq=ctx.can(Permission.NETWORK_COMPARE)))
