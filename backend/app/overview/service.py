"""The overview screens' data, computed here and only drawn by the frontend (ADR 0007).

- `context` — the demo's «today», data up to which day, the next stock count;
- `network` — the network's home: found potential, confirmed effect, decisions waiting, the trend, who loses
  most, problems common to several restaurants;
- `restaurant` — «Моя неделя» of one restaurant: potential, change on the week, the summary, three actions,
  losses by process, KPIs against the network, results of the work;
- `restaurants` — the list of all restaurants for HQ;
- `badges` — counters of the menu.

Visibility comes from row-level security: a director's queries simply see their restaurant (and the network's
KPI row), so the same functions serve both roles.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import words
from app.core.errors import NotFoundError
from app.core.period import Period
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.imports.service import freshness
from app.insights.models import FindingStatus
from app.insights.service import FindingWork, list_findings
from app.insights.work import WorkStage
from app.operations.models import InventoryCount, Sale
from app.overview.models import KpiSnapshot, TrendPoint
from app.tasks.models import OutcomeVerdict, Task, TaskStatus
from app.tenancy.models import Restaurant

ZERO = Decimal(0)
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)

PROCESSES: list[tuple[str, str]] = [
    ("purchasing", "Закупка"),
    ("receiving", "Приемка"),
    ("storage", "Хранение"),
    ("production", "Производство (ТТК)"),
    ("writeoffs", "Списания"),
    ("inventory", "Инвентаризация"),
    ("accounting", "Учет и данные"),
    ("planning", "Планирование запасов"),
]
PROCESS_TITLE = dict(PROCESSES)
PROCESS_SHORT = {"production": "Производство", "planning": "Запасы", "accounting": "Учет"}
PLACES = ("ресторане", "ресторанах", "ресторанах")
# A process with open problems worth this much a month is critical, below — a warning.
PROCESS_CRITICAL_RUB = Decimal(25_000)
# «Три дела недели»: money × how sure we are.
CONFIDENCE_WEIGHT = {"high": Decimal(1), "medium": Decimal("0.7"), "low": Decimal("0.4")}


# ------------------------------------------------------------------ context


@dataclass(frozen=True)
class Context:
    today: date
    data_until: date | None
    next_count_on: date | None


def context(session: Session, today: date) -> Context:
    data_until = session.execute(select(func.max(Sale.day))).scalar_one_or_none()
    days = sorted(session.execute(select(InventoryCount.day).distinct()).scalars())
    next_count = None
    if len(days) >= 2:
        gap = int(median((b - a).days for a, b in pairwise(days)))
        next_count = days[-1] + timedelta(days=gap)
        while next_count < today:
            next_count += timedelta(days=gap)
    return Context(today, data_until, next_count)


# ------------------------------------------------------------------ shared pieces


def _open(session: Session, today: date, restaurant_id: UUID | None = None) -> list[FindingWork]:
    """Open checked findings, the most expensive first (row-level security limits what a director gets)."""
    return [
        fw
        for fw in list_findings(session, today=today, restaurant_id=restaurant_id)
        if fw.finding.status in OPEN
    ]


def _sum(items: list[FindingWork], kind: str | None = None) -> Decimal:
    return sum(
        (fw.finding.effect_rub_month or ZERO for fw in items if kind is None or fw.finding.kind == kind),
        ZERO,
    )


@dataclass
class Trend:
    labels: list[str] = field(default_factory=list)  # week starts, «ДД.ММ»
    week_ends: list[date] = field(default_factory=list)
    on_table: list[Decimal] = field(default_factory=list)
    returned: list[Decimal] = field(default_factory=list)
    open_findings: list[int] = field(default_factory=list)

    @property
    def first(self) -> Decimal | None:
        return self.on_table[0] if self.on_table else None

    @property
    def last(self) -> Decimal | None:
        return self.on_table[-1] if self.on_table else None

    @property
    def change(self) -> Decimal | None:
        """How much «найденный потенциал» moved over the line, ₽ a month (negative: it went down — better)."""
        return None if len(self.on_table) < 2 else self.on_table[-1] - self.on_table[0]

    @property
    def change_pct(self) -> int | None:
        if self.change is None or not self.first:
            return None
        return int((abs(self.change) / self.first * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    @property
    def span(self) -> str:
        """«12 недель»: how long the line is."""
        return words.plural(max(len(self.on_table) - 1, 1), ("неделю", "недели", "недель"))

    @property
    def answer(self) -> str:
        """«Становится ли лучше?» in words."""
        first, last = self.first, self.last
        if self.change is None or first is None or last is None:
            return "История появится после двух недель пересчетов."
        if last < first:
            return (
                f"Да. За {self.span} найденный потенциал снизился с {words.rub(first)} до "
                f"{words.rub(last)} в месяц."
            )
        if last == first:
            return f"Пока нет. За {self.span} найденный потенциал не изменился: {words.per_month(last)}."
        return (
            f"Нет. За {self.span} найденный потенциал вырос с {words.rub(first)} до {words.rub(last)} "
            "в месяц — появились новые проблемы."
        )


def trend_of(session: Session, restaurant_id: UUID | None, period: Period | None) -> Trend:
    """Weekly points; with a period — the weeks inside it plus the one before (the change is over the period),
    at least two points so a line is still a line."""
    query = select(TrendPoint).order_by(TrendPoint.week_end)
    query = query.where(
        TrendPoint.restaurant_id.is_(None)
        if restaurant_id is None
        else TrendPoint.restaurant_id == restaurant_id
    )
    points = list(session.execute(query).scalars())
    if period is not None and points:
        keep = [
            i
            for i, p in enumerate(points)
            if period.date_from - timedelta(days=7) <= p.week_end <= period.date_to
        ]
        if not keep:
            keep = [len(points) - 1]
        a, b = keep[0], keep[-1] + 1
        if b - a < 2:
            a = max(0, b - 2)
        points = points[a:b]
    t = Trend()
    for p in points:
        t.labels.append((p.week_end - timedelta(days=6)).strftime("%d.%m"))
        t.week_ends.append(p.week_end)
        t.on_table.append(p.losses + p.potential)
        t.returned.append(p.returned)
        t.open_findings.append(p.open_findings)
    return t


def _last_two(session: Session, restaurant_id: UUID | None) -> tuple[TrendPoint | None, TrendPoint | None]:
    query = select(TrendPoint).order_by(TrendPoint.week_end.desc()).limit(2)
    query = query.where(
        TrendPoint.restaurant_id.is_(None)
        if restaurant_id is None
        else TrendPoint.restaurant_id == restaurant_id
    )
    points = list(session.execute(query).scalars())
    return (points[0] if points else None, points[1] if len(points) > 1 else None)


def _confirmed(session: Session, restaurant_id: UUID | None = None) -> Decimal:
    """Profit the changes already gave, ₽/month: checks that worked and task results outside checks."""
    total = ZERO
    for e in session.execute(select(Experiment).where(Experiment.verdict == Verdict.CONFIRMED)).scalars():
        if restaurant_id is None:
            total += e.effect_rub_month or ZERO
        elif restaurant_id in e.test_restaurant_ids:
            total += (e.effect_rub_month or ZERO) / len(e.test_restaurant_ids)
    query = select(Task).where(Task.outcome_verdict == OutcomeVerdict.CONFIRMED, Task.experiment_id.is_(None))
    if restaurant_id is not None:
        query = query.where(Task.restaurant_id == restaurant_id)
    total += sum((t.outcome_effect_rub_month or ZERO for t in session.execute(query).scalars()), ZERO)
    return total.quantize(Decimal(1))


def _late(t: Task, today: date) -> bool:
    return t.status != TaskStatus.DONE and t.due_on < today


# ------------------------------------------------------------------ network


@dataclass
class RankRow:
    restaurant_id: UUID
    code: str
    name: str
    losses: Decimal
    delta: Decimal | None  # against the week before; None without history
    top_problem: str | None


@dataclass
class Common:
    key: str
    process: str
    title: str
    where: str
    losses: Decimal | None
    note: str
    finding_id: UUID | None


@dataclass
class MatrixCell:
    process: str
    losses: Decimal  # open checked problems of the process, ₽ a month
    count: int  # problems, with those not estimated in rubles
    status: str  # good | warning | critical (same rule as a restaurant's process map)


@dataclass
class MatrixRow:
    id: UUID
    code: str
    name: str
    total: Decimal
    cells: list[MatrixCell]


@dataclass
class Network:
    restaurants: int
    losses: Decimal
    potential: Decimal
    found_count: int
    confirmed: Decimal
    completed_checks: int
    checks_waiting: int
    overdue_tasks: int
    trend: Trend
    ranking: list[RankRow]
    common: list[Common]
    matrix: list[MatrixRow]  # restaurants × processes (docs/10, 4.3), the costliest restaurant first
    matrix_answer: str
    kpi: "Kpis | None"  # the network's food cost and write-offs (the engine's last snapshot)
    overpay: Decimal  # open purchasing problems: paying suppliers more than needed, ₽ a month


def _process_losses(items: list[FindingWork]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for fw in items:
        if fw.finding.kind == "problem":
            out[fw.finding.process] += fw.finding.effect_rub_month or ZERO
    return out


def _status(items: list[FindingWork], process: str) -> str:
    problems = [fw for fw in items if fw.finding.kind == "problem" and fw.finding.process == process]
    if not problems:
        return "good"
    return "critical" if _sum(problems) >= PROCESS_CRITICAL_RUB else "warning"


def _matrix_answer(matrix: list[MatrixRow]) -> str:
    """The costliest process across the restaurants, in words."""
    by_process: dict[str, Decimal] = defaultdict(lambda: ZERO)
    places: dict[str, int] = defaultdict(int)
    for row in matrix:
        for c in row.cells:
            if c.count:
                by_process[c.process] += c.losses
                places[c.process] += 1
    if not places:
        return "Открытых проблем в ресторанах нет: все процессы в норме."
    top = max(places, key=lambda p: (by_process[p], places[p]))
    where = words.plural(places[top], PLACES)
    if not by_process[top]:
        return f"Проблемы без оценки в рублях: больше всего — «{PROCESS_TITLE[top]}», в {where}."
    return (
        f"Больше всего теряем на процессе «{PROCESS_TITLE[top]}»: {words.per_month(by_process[top])} "
        f"в {where}. Нажмите на ячейку — откроются находки ресторана."
    )


def network(session: Session, period: Period, today: date) -> Network:
    places = list(session.execute(select(Restaurant).order_by(Restaurant.code)).scalars())
    items = _open(session, today)
    by_place: dict[UUID | None, list[FindingWork]] = defaultdict(list)
    for fw in items:
        by_place[fw.finding.restaurant_id].append(fw)

    ranking = []
    for r in places:
        mine = by_place[r.id]
        problems = [fw for fw in mine if fw.finding.kind == "problem"]
        _, before = _last_two(session, r.id)
        losses = _sum(problems)
        ranking.append(
            RankRow(
                r.id,
                r.code,
                r.name,
                losses,
                losses - before.losses if before is not None else None,
                problems[0].finding.title if problems else None,
            )
        )
    ranking.sort(key=lambda x: (-x.losses, x.code))

    common = [
        Common(
            key=str(fw.finding.id),
            process=fw.finding.process,
            title=fw.finding.title,
            where="Во всех ресторанах",
            losses=fw.finding.effect_rub_month,
            note=fw.finding.effect_note or "сумму пока не оценить",
            finding_id=fw.finding.id,
        )
        for fw in by_place[None]
    ]
    for process, title in PROCESSES:
        hit = [r for r in places if _status(by_place[r.id], process) != "good"]
        if len(hit) >= 2:
            losses = sum((_process_losses(by_place[r.id])[process] for r in hit), ZERO)
            common.append(
                Common(
                    key=process,
                    process=process,
                    title=f"{title}: проблемы в {words.plural(len(hit), PLACES)}",
                    where=", ".join(r.name.removeprefix("Ресторан ") for r in hit),
                    losses=losses or None,
                    note="пробел в данных",
                    finding_id=None,
                )
            )
    common.sort(key=lambda c: -(c.losses or ZERO))

    matrix = []
    for r in places:
        mine = by_place[r.id]
        cells = []
        for process, _ in PROCESSES:
            problems = [fw for fw in mine if fw.finding.kind == "problem" and fw.finding.process == process]
            cells.append(MatrixCell(process, _sum(problems), len(problems), _status(mine, process)))
        matrix.append(MatrixRow(r.id, r.code, r.name, sum((c.losses for c in cells), ZERO), cells))
    matrix.sort(key=lambda row: (-row.total, -sum(c.count for c in row.cells), row.code))
    matrix_answer = _matrix_answer(matrix)
    network_kpi = session.execute(
        select(KpiSnapshot).where(KpiSnapshot.restaurant_id.is_(None))
    ).scalar_one_or_none()

    tasks = list(session.execute(select(Task)).scalars())
    return Network(
        restaurants=len(places),
        losses=_sum(items, "problem"),
        potential=_sum(items, "opportunity"),
        found_count=sum(1 for fw in items if fw.finding.effect_rub_month is not None),
        confirmed=_confirmed(session),
        completed_checks=session.execute(
            select(func.count())
            .select_from(Experiment)
            .where(Experiment.status == ExperimentStatus.COMPLETED)
        ).scalar_one(),
        checks_waiting=session.execute(
            select(func.count()).select_from(Experiment).where(Experiment.status == ExperimentStatus.PROPOSED)
        ).scalar_one(),
        overdue_tasks=sum(1 for t in tasks if _late(t, today)),
        trend=trend_of(session, None, period),
        ranking=ranking,
        common=common,
        matrix=matrix,
        matrix_answer=matrix_answer,
        kpi=_kpis(network_kpi),
        overpay=_sum(
            [fw for fw in items if fw.finding.kind == "problem" and fw.finding.process == "purchasing"]
        ),
    )


# ------------------------------------------------------------------ restaurant


@dataclass
class ProcessLosses:
    process: str
    title: str
    losses: Decimal
    findings: list[FindingWork]


@dataclass
class Kpis:
    food_cost_actual: Decimal | None
    food_cost_theory: Decimal | None
    write_offs_share: Decimal | None
    food_cost_from: date | None
    food_cost_to: date | None
    write_offs_from: date | None = None
    write_offs_to: date | None = None


@dataclass
class RestaurantWeek:
    restaurant: Restaurant
    losses: Decimal
    potential: Decimal
    found_count: int
    delta_week: Decimal | None
    digest: str
    digest_findings: list[FindingWork]
    actions: list[FindingWork]  # the three for the director to take (not taken yet)
    top: list[FindingWork]  # the three most valuable whatever their stage (HQ's read-only view)
    processes: list[ProcessLosses]
    fine_processes: list[str]
    kpi: Kpis | None
    network_kpi: Kpis | None
    kpi_answer: str | None
    done_tasks: list[Task]
    results_answer: str


def _rank(items: list[FindingWork]) -> list[FindingWork]:
    priced = [fw for fw in items if fw.finding.effect_rub_month]
    return sorted(
        priced,
        key=lambda fw: (
            -(fw.finding.effect_rub_month or ZERO)
            * CONFIDENCE_WEIGHT.get(fw.finding.confidence or "medium", Decimal("0.7"))
        ),
    )


def _kpis(row: KpiSnapshot | None) -> Kpis | None:
    if row is None:
        return None
    return Kpis(
        row.food_cost_actual,
        row.food_cost_theory,
        row.write_offs_share,
        row.food_cost_from,
        row.food_cost_to,
        row.write_offs_from,
        row.write_offs_to,
    )


def _kpi_answer(me: Kpis | None, net: Kpis | None) -> str | None:
    if not me or not net or me.food_cost_actual is None or net.food_cost_actual is None:
        return None
    diff = (me.food_cost_actual - net.food_cost_actual) * 100
    text = f"Фудкост на {words.number(abs(diff))} п.п. {'выше' if diff >= 0 else 'ниже'} среднего по сети"
    if me.write_offs_share and net.write_offs_share:
        ratio = me.write_offs_share / net.write_offs_share
        if ratio >= 1:
            text += f", списания — в {words.number(ratio)} раза больше"
        else:
            text += f", списания — в {words.number(1 / ratio)} раза меньше"
    return text + "."


def _digest(name: str, delta: Decimal | None, ranked: list[FindingWork], late: int) -> str:
    parts = []
    if delta is not None and delta != 0:
        parts.append(
            f"За неделю найденный потенциал {'вырос' if delta > 0 else 'снизился'} на {words.rub(abs(delta))}"
            + (": появились новые проблемы." if delta > 0 else ": часть проблем уже решена.")
        )
    if ranked:
        top = ranked[0].finding
        parts.append(f"Главное — «{top.title}»: {words.per_month(top.effect_rub_month or ZERO)}.")
        if len(ranked) > 1:
            parts.append("Еще: " + ", ".join(f"«{fw.finding.title}»" for fw in ranked[1:3]) + ".")
    else:
        parts.append(f"В ресторане «{name}» открытых проблем с оценкой в рублях нет.")
    if late:
        parts.append(f"Просрочено {words.plural(late, ('задача', 'задачи', 'задач'))}.")
    return " ".join(parts)


def _results_answer(done: list[Task]) -> str:
    if not done:
        return "Выполненных задач пока нет. Результат в рублях появится после ближайшей инвентаризации."
    confirmed = sum(
        (t.outcome_effect_rub_month or ZERO for t in done if t.outcome_verdict == OutcomeVerdict.CONFIRMED),
        ZERO,
    )
    pending = sum(1 for t in done if t.outcome_verdict in (None, OutcomeVerdict.PENDING))
    parts = []
    if confirmed:
        parts.append(f"Ваши задачи уже приносят +{words.per_month(confirmed)}")
    if pending:
        parts.append(
            f"по {words.plural(pending, ('задаче', 'задачам', 'задачам'))} результат посчитаем "
            "после инвентаризации"
        )
    if not parts:
        return "Выполненные задачи пока не дали измеримого результата."
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def restaurant_by_code(session: Session, code: str) -> Restaurant:
    r = session.execute(select(Restaurant).where(Restaurant.code == code)).scalar_one_or_none()
    if r is None:  # missing or not visible to the caller (row-level security): the same answer
        raise NotFoundError("Ресторан не найден")
    return r


def restaurant(session: Session, code: str, today: date) -> RestaurantWeek:
    r = restaurant_by_code(session, code)
    items = _open(session, today, r.id)
    ranked = _rank(items)
    now, before = _last_two(session, r.id)
    delta = (now.losses + now.potential) - (before.losses + before.potential) if now and before else None
    tasks = list(session.execute(select(Task).where(Task.restaurant_id == r.id)).scalars())
    late = sum(1 for t in tasks if _late(t, today))
    by_process = _process_losses(items)
    processes = [
        ProcessLosses(
            p,
            title,
            by_process[p],
            [fw for fw in items if fw.finding.kind == "problem" and fw.finding.process == p],
        )
        for p, title in PROCESSES
        if by_process.get(p)
    ]
    processes.sort(key=lambda x: -x.losses)
    fine = [title for p, title in PROCESSES if not by_process.get(p)]
    snapshots = {k.restaurant_id: k for k in session.execute(select(KpiSnapshot)).scalars()}
    me, net = _kpis(snapshots.get(r.id)), _kpis(snapshots.get(None))
    done = sorted(
        (t for t in tasks if t.status == TaskStatus.DONE), key=lambda t: t.done_on or today, reverse=True
    )
    return RestaurantWeek(
        restaurant=r,
        losses=_sum(items, "problem"),
        potential=_sum(items, "opportunity"),
        found_count=sum(1 for fw in items if fw.finding.effect_rub_month is not None),
        delta_week=delta,
        digest=_digest(r.name, delta, ranked, late),
        digest_findings=ranked[:3],
        actions=[fw for fw in ranked if fw.work.stage == WorkStage.NEW][:3],
        top=ranked[:3],
        processes=processes,
        fine_processes=fine,
        kpi=me,
        network_kpi=net,
        kpi_answer=_kpi_answer(me, net),
        done_tasks=done,
        results_answer=_results_answer(done),
    )


# ------------------------------------------------------------------ restaurants (HQ)


@dataclass
class RestaurantRow:
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


TEMPLATE_WORDS = {
    "sales": "продажи",
    "receipts": "закупки",
    "write_offs": "списания",
    "inventory_counts": "пересчеты",
}


def restaurants(session: Session, today: date) -> list[RestaurantRow]:
    items = _open(session, today)
    by_place: dict[UUID | None, list[FindingWork]] = defaultdict(list)
    for fw in items:
        by_place[fw.finding.restaurant_id].append(fw)
    tasks = list(session.execute(select(Task)).scalars())
    snapshots = {k.restaurant_id: k for k in session.execute(select(KpiSnapshot)).scalars()}
    stale: dict[UUID, str] = {}
    for f in freshness(session, today=today):
        if f["status"] != "good" and f["restaurant_id"] not in stale:
            what = TEMPLATE_WORDS.get(f["template"], f["template"])
            stale[f["restaurant_id"]] = (
                f"{what} по {f['last_date']:%d.%m}" if f["last_date"] else f"нет: {what}"
            )
    rows = []
    for r in session.execute(select(Restaurant).order_by(Restaurant.code)).scalars():
        mine = by_place[r.id]
        own = [t for t in tasks if t.restaurant_id == r.id]
        _, before = _last_two(session, r.id)
        losses = _sum(mine, "problem")
        rows.append(
            RestaurantRow(
                id=r.id,
                code=r.code,
                name=r.name,
                city=r.city,
                losses=losses,
                potential=_sum(mine, "opportunity"),
                delta=losses - before.losses if before is not None else None,
                food_cost=snapshots[r.id].food_cost_actual if r.id in snapshots else None,
                late=sum(1 for t in own if _late(t, today)),
                tasks_done=sum(1 for t in own if t.status == TaskStatus.DONE),
                tasks_total=len(own),
                bad_processes=sum(1 for p, _ in PROCESSES if _status(mine, p) != "good"),
                stale_data=stale.get(r.id),
            )
        )
    return rows


# ------------------------------------------------------------------ badges


def badges(session: Session, today: date, *, hq: bool) -> dict[str, Any]:
    """Asked on every page: counted in the database, not by reading every task (architecture review, p. 19).
    The same rule as `_late`: not done and past the due date."""

    def count(*where: Any) -> int:
        return session.execute(select(func.count()).select_from(Task).where(*where)).scalar_one()

    if hq:
        waiting = session.execute(
            select(func.count()).select_from(Experiment).where(Experiment.status == ExperimentStatus.PROPOSED)
        ).scalar_one()
        late = count(Task.status != TaskStatus.DONE, Task.due_on < today)
        return {"inbox": waiting + late, "open_tasks": 0}
    return {"inbox": 0, "open_tasks": count(Task.status != TaskStatus.DONE)}


# ------------------------------------------------------------------ the findings list


@dataclass
class Group:
    key: str  # problem | opportunity | unestimated
    title: str
    count: int
    total: Decimal
    items: list[FindingWork]


@dataclass
class Board:
    kinds: list[tuple[str, int, Decimal]]  # (kind, count, total) under the filters except the kind itself
    stage_counts: dict[str, int]
    late_count: int
    processes: list[str]  # processes that have findings at all (for the filter)
    groups: list[Group]
    max_effect: Decimal


GROUP_TITLE = {
    "problem": "Где теряем",
    "opportunity": "Где можно заработать",
    "unestimated": "Без оценки в рублях — но важно для точности",
}


def board(
    session: Session,
    today: date,
    *,
    kind: str | None = None,
    process: str | None = None,
    restaurant: str | None = None,  # a restaurant id, or "net" for network-wide findings
    stage: str | None = None,
    late: bool = False,
) -> Board:
    """The findings list: every filter, count and sum is applied here; the most expensive first."""
    scope = list_findings(session, today=today)

    def keep(fw: FindingWork) -> bool:
        f = fw.finding
        where = "net" if f.restaurant_id is None else str(f.restaurant_id)
        return (
            (process is None or f.process == process)
            and (restaurant is None or where == restaurant)
            and (stage is None or fw.work.stage == stage)
            and (not late or fw.work.tasks_late > 0)
        )

    filtered = [fw for fw in scope if keep(fw)]
    kinds = [
        (
            k,
            sum(1 for fw in filtered if fw.finding.kind == k),
            _sum([fw for fw in filtered if fw.finding.kind == k]),
        )
        for k in ("problem", "opportunity")
    ]
    shown = [k for k in ("problem", "opportunity") if kind in (None, k)]
    groups = [
        Group(k, GROUP_TITLE[k], len(items), _sum(items), items)
        for k in shown
        for items in [
            [fw for fw in filtered if fw.finding.kind == k and fw.finding.effect_rub_month is not None]
        ]
    ]
    unestimated = [fw for fw in filtered if fw.finding.effect_rub_month is None and fw.finding.kind in shown]
    groups.append(Group("unestimated", GROUP_TITLE["unestimated"], len(unestimated), ZERO, unestimated))
    stages = {s.value: sum(1 for fw in scope if fw.work.stage == s) for s in WorkStage}
    return Board(
        kinds=kinds,
        stage_counts={"all": len(scope), **stages},
        late_count=sum(1 for fw in scope if fw.work.tasks_late > 0),
        processes=[p for p, _ in PROCESSES if any(fw.finding.process == p for fw in scope)],
        groups=[g for g in groups if g.items],
        max_effect=max((fw.finding.effect_rub_month or ZERO for fw in filtered), default=ZERO),
    )
