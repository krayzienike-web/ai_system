"""Overview screens (ADR 0007): figures, rankings and conclusions come from `service`; the screens draw."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import SessionDep, require
from app.core.period import PeriodError, PeriodPreset, TodayDep, resolve_period
from app.insights.api import FindingOut, findings_out
from app.insights.service import FindingWork
from app.insights.work import WorkStage
from app.overview import service
from app.overview.period import PeriodDep, last_count_day
from app.tasks.api import TaskOut, tasks_out
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["overview"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]
CanCompare = Annotated[AccessContext, Depends(require(Permission.NETWORK_COMPARE))]

DUE_OPTIONS = [("3 дня", 3), ("Неделя", 7), ("2 недели", 14)]
PERIOD_TITLES = [
    (PeriodPreset.WEEK, "Прошлая неделя"),
    (PeriodPreset.PREV_WEEK, "Неделя до нее"),
    (PeriodPreset.FOUR_WEEKS, "4 недели"),
    (PeriodPreset.THIRTEEN_WEEKS, "13 недель"),
    (PeriodPreset.MONTH, "Прошлый месяц"),
    (PeriodPreset.QUARTER, "Прошлый квартал"),
    (PeriodPreset.SINCE_COUNT, "С последней инвентаризации"),
]


class DueOption(BaseModel):
    label: str
    days: int
    due_on: date


class PeriodOption(BaseModel):
    preset: PeriodPreset
    title: str
    date_from: date
    date_to: date


class ContextOut(BaseModel):
    today: date
    data_until: date | None
    next_count_on: date | None
    due_options: list[DueOption]  # deadlines offered for a new task
    periods: list[PeriodOption]  # the period picker's presets, resolved for today


class TrendOut(BaseModel):
    labels: list[str]
    week_ends: list[date]
    on_table: list[Decimal]
    returned: list[Decimal]
    open_findings: list[int]
    # The line in words and figures, so the screens compute nothing (ADR 0007).
    change: Decimal | None  # last − first, ₽ a month; negative is better
    change_pct: int | None  # |change| / first, %
    span: str  # «12 недель»
    answer: str  # «Становится ли лучше?»

    @classmethod
    def of(cls, t: service.Trend) -> "TrendOut":
        return cls(**t.__dict__, change=t.change, change_pct=t.change_pct, span=t.span, answer=t.answer)


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


class KpiOut(BaseModel):
    food_cost_actual: Decimal | None
    food_cost_theory: Decimal | None
    write_offs_share: Decimal | None
    food_cost_from: date | None
    food_cost_to: date | None
    write_offs_from: date | None = None
    write_offs_to: date | None = None


class ProcessTitleOut(BaseModel):
    process: str
    title: str
    short: str  # for a narrow column


class MatrixCellOut(BaseModel):
    process: str
    losses: Decimal
    count: int
    status: Literal["good", "warning", "critical"]


class MatrixRowOut(BaseModel):
    id: UUID
    code: str
    name: str
    short_name: str  # «на Тверской»: the network's restaurants all start with «Ресторан»
    total: Decimal
    cells: list[MatrixCellOut]  # in the order of `processes`


class NetworkOut(BaseModel):
    restaurants: int
    losses: Decimal
    potential: Decimal
    on_table: Decimal  # «найденный потенциал»: losses + potential, ₽ a month
    on_table_year: Decimal
    found_count: int
    confirmed: Decimal
    completed_checks: int
    checks_waiting: int
    overdue_tasks: int
    trend: TrendOut
    ranking: list[RankOut]
    common: list[CommonOut]
    processes: list[ProcessTitleOut]  # the columns of `matrix`
    matrix: list[MatrixRowOut]  # restaurants × processes, the costliest restaurant first
    matrix_answer: str
    kpi: KpiOut | None  # the network's food cost and write-offs, as of the engine's last run
    overpay: Decimal  # open purchasing problems, ₽ a month


class ProcessOut(BaseModel):
    process: str
    title: str
    losses: Decimal
    findings: list[FindingOut]


class RestaurantRef(BaseModel):
    id: UUID
    code: str
    name: str
    city: str | None


class WeekOut(BaseModel):
    restaurant: RestaurantRef
    losses: Decimal
    potential: Decimal
    on_table: Decimal  # «найденный потенциал»: losses + potential, ₽ a month
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


def _period_options(session: Session, today: date) -> list[PeriodOption]:
    """The picker's presets with their dates; «с последней инвентаризации» only once there is a count."""
    last_count = last_count_day(session, today)
    options = []
    for p, title in PERIOD_TITLES:
        try:
            r = resolve_period(today, p, last_count=last_count)
        except PeriodError:
            continue
        options.append(PeriodOption(preset=p, title=title, date_from=r.date_from, date_to=r.date_to))
    return options


@router.get("/overview/context")
def get_context(ctx: CanRead, session: SessionDep, today: TodayDep) -> ContextOut:
    c = service.context(session, today)
    return ContextOut(
        today=c.today,
        data_until=c.data_until,
        next_count_on=c.next_count_on,
        due_options=[
            DueOption(label=label, days=days, due_on=today + timedelta(days=days))
            for label, days in DUE_OPTIONS
        ],
        periods=_period_options(session, today),
    )


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
        trend=TrendOut.of(n.trend),
        on_table=n.losses + n.potential,
        on_table_year=(n.losses + n.potential) * 12,
        ranking=[RankOut(**r.__dict__) for r in n.ranking],
        common=[CommonOut(**c.__dict__) for c in n.common],
        processes=[
            ProcessTitleOut(process=p, title=t, short=service.PROCESS_SHORT.get(p, t))
            for p, t in service.PROCESSES
        ],
        matrix=[
            MatrixRowOut(
                id=r.id,
                code=r.code,
                name=r.name,
                short_name=r.name.removeprefix("Ресторан "),
                total=r.total,
                cells=[MatrixCellOut(**c.__dict__) for c in r.cells],
            )
            for r in n.matrix
        ],
        matrix_answer=n.matrix_answer,
        kpi=KpiOut(**n.kpi.__dict__) if n.kpi else None,
        overpay=n.overpay,
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
        on_table=w.losses + w.potential,
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


class KindTotal(BaseModel):
    kind: str
    count: int
    total: Decimal


class GroupOut(BaseModel):
    key: str
    title: str
    count: int
    total: Decimal
    items: list[FindingOut]


class BoardOut(BaseModel):
    kinds: list[KindTotal]
    stage_counts: dict[str, int]
    late_count: int
    processes: list[str]
    groups: list[GroupOut]
    max_effect: Decimal


@router.get("/overview/findings")
def get_board(
    ctx: CanRead,
    session: SessionDep,
    today: TodayDep,
    kind: Annotated[Literal["problem", "opportunity"] | None, Query()] = None,
    process: Annotated[str | None, Query()] = None,
    restaurant: Annotated[str | None, Query(description="restaurant id, or `net` for network-wide")] = None,
    stage: Annotated[WorkStage | None, Query()] = None,
    late: Annotated[bool, Query()] = False,
) -> BoardOut:
    b = service.board(
        session, today, kind=kind, process=process, restaurant=restaurant, stage=stage, late=late
    )
    return BoardOut(
        kinds=[KindTotal(kind=k, count=c, total=t) for k, c, t in b.kinds],
        stage_counts=b.stage_counts,
        late_count=b.late_count,
        processes=b.processes,
        groups=[
            GroupOut(
                key=g.key,
                title=g.title,
                count=g.count,
                total=g.total,
                items=findings_out(session, ctx, g.items),
            )
            for g in b.groups
        ],
        max_effect=b.max_effect,
    )
