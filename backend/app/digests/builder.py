"""The weekly digest's content, computed by the code (docs/08, part 1; stage 6).

`build` gathers, for one restaurant or the network and one week:
- the KPIs, against the previous digest and (for a restaurant) the network's average — never another one;
- the map of the 8 processes: status, an index 0–100 and its change against the previous digest;
- 3–5 problems and 3–5 opportunities with the largest «effect × confidence», one per object;
- the total «on the table», what improved (tasks done in the week, processes whose index went up), the
  risks of the next days (stock-outs, M6), and the date of the last stock count (recipe and shortage
  findings stand on it).

Everything is JSON-ready and formatted like the screens: the texts (by rules now, by the model when it is on)
quote these figures and nothing else. A restaurant's digest holds only what its director may see: reviewed
findings of the restaurant, no per-restaurant table of the network.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import words
from app.insights.service import FindingWork
from app.operations.models import InventoryCount
from app.overview import service as overview
from app.overview.models import KpiSnapshot
from app.tasks.models import OutcomeVerdict, Task, TaskStatus
from app.tenancy.models import Restaurant

ZERO = Decimal(0)
ITEMS_MIN, ITEMS_MAX = 3, 5
# A process loses this much a month (× the restaurants, for the network): index 50 — the edge of «critical».
UNPRICED_INDEX = 90  # open problems without a ruble estimate yet


@dataclass(frozen=True)
class Week:
    start: date  # Monday
    end: date  # Sunday

    @classmethod
    def before(cls, day: date) -> "Week":
        """The last full week (Monday–Sunday) before `day` — what a Monday's digest is about (Q24)."""
        monday = day - timedelta(days=day.weekday())
        return cls(monday - timedelta(days=7), monday - timedelta(days=1))


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{words.number(value, 0)} ₽"


def pct(share: Decimal | None, places: int = 1) -> str | None:
    return None if share is None else words.percent(share, places)


def index(losses: Decimal, priced: bool, unpriced: bool, threshold: Decimal) -> int:
    """0–100: 100 — no open problems; 50 — the process loses `threshold` a month; 0 — twice that."""
    if not priced and not unpriced:
        return 100
    if not priced:
        return UNPRICED_INDEX
    value = 100 - 50 * losses / threshold
    return int(max(Decimal(0), min(Decimal(99), value)).quantize(Decimal(1), ROUND_HALF_UP))


def status(idx: int) -> str:
    return "good" if idx == 100 else ("warning" if idx > 50 else "critical")


def _object(fw: FindingWork) -> str:
    """What a finding is about — the item of its key («M1:R01:P01» → P01) — so one object appears once."""
    parts = (fw.finding.key or "").split(":")
    return parts[2] if len(parts) > 2 else str(fw.finding.id)


def _view(fw: FindingWork, for_director: bool) -> dict[str, Any]:
    view = dict(fw.finding.view or {})
    if for_director and view.get("table_names_restaurants"):  # the per-restaurant table is the HQ's
        view.pop("table", None)
        view.pop("table_names_restaurants", None)
    return view


def _item(fw: FindingWork, for_director: bool) -> dict[str, Any]:
    f = fw.finding
    view = _view(fw, for_director)
    return {
        "finding_id": str(f.id),
        "title": f.title,
        "process": overview.PROCESS_TITLE.get(f.process, f.process),
        "effect_per_month": money(f.effect_rub_month),
        "headline": f.headline,
        "summary": view.get("summary"),
        "causes": view.get("causes") or [],
        "actions": list(f.actions),
        "taken": fw.work.stage != "new",
    }


def _pick(ranked: list[FindingWork], kind: str, taken: set[str]) -> list[FindingWork]:
    out = []
    for fw in ranked:
        if fw.finding.kind != kind or _object(fw) in taken:
            continue
        taken.add(_object(fw))
        out.append(fw)
        if len(out) == ITEMS_MAX:
            break
    return out


def _kpis(row: KpiSnapshot | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "food_cost_actual": pct(row.food_cost_actual),
        "food_cost_theory": pct(row.food_cost_theory),
        "write_offs_share_of_revenue": pct(row.write_offs_share, 2),
        "food_cost_period": f"{row.food_cost_from:%d.%m.%Y}–{row.food_cost_to:%d.%m.%Y}"
        if row.food_cost_from and row.food_cost_to
        else None,
        "revenue": money(row.revenue),
    }


def build(
    session: Session, *, restaurant_id: UUID | None, week: Week, today: date, previous: dict[str, Any] | None
) -> dict[str, Any]:
    """The digest of one restaurant (`restaurant_id`) or of the network (None) for `week`."""
    for_director = restaurant_id is not None
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}
    items = overview.open_findings(session, today, restaurant_id)
    if restaurant_id is not None:
        items = [fw for fw in items if fw.finding.restaurant_id == restaurant_id]
    ranked = overview.rank(items)
    threshold = overview.PROCESS_CRITICAL_RUB * (1 if restaurant_id else max(1, len(places)))

    before = {p["process"]: p for p in (previous or {}).get("processes", [])}
    processes = []
    for code, title in overview.PROCESSES:
        mine = [fw for fw in items if fw.finding.kind == "problem" and fw.finding.process == code]
        losses = sum((fw.finding.effect_rub_month or ZERO for fw in mine), ZERO)
        idx = index(losses, any(fw.finding.effect_rub_month for fw in mine), bool(mine), threshold)
        was = before.get(code, {}).get("index")
        processes.append(
            {
                "process": code,
                "title": title,
                "status": status(idx),
                "index": idx,
                "change": None if was is None else idx - was,
                "losses_per_month": money(losses) if losses else None,
                "open_problems": len(mine),
            }
        )

    taken: set[str] = set()
    problems = _pick(ranked, "problem", taken)
    opportunities = _pick(ranked, "opportunity", taken)
    losses = sum((fw.finding.effect_rub_month or ZERO for fw in items if fw.finding.kind == "problem"), ZERO)
    potential = sum(
        (fw.finding.effect_rub_month or ZERO for fw in items if fw.finding.kind == "opportunity"), ZERO
    )

    snapshots = {k.restaurant_id: k for k in session.execute(select(KpiSnapshot)).scalars()}
    kpis = _kpis(snapshots.get(restaurant_id))

    tasks = select(Task).where(Task.status == TaskStatus.DONE, Task.done_on.between(week.start, week.end))
    if restaurant_id is not None:
        tasks = tasks.where(Task.restaurant_id == restaurant_id)
    done = list(session.execute(tasks).scalars())
    confirmed = sum(
        (t.outcome_effect_rub_month or ZERO for t in done if t.outcome_verdict == OutcomeVerdict.CONFIRMED),
        ZERO,
    )
    improved = {
        "tasks_done": len(done),
        "tasks": [t.title for t in done[:ITEMS_MAX]],
        "confirmed_effect_per_month": money(confirmed) if confirmed else None,
        "processes_better": [str(p["title"]) for p in processes if int(p["change"] or 0) > 0],
    }
    # Stock-outs of the next days: the priced ones first, then those without an estimate.
    stock = sorted(
        (fw for fw in items if fw.finding.module == "M6"),
        key=lambda fw: -(fw.finding.effect_rub_month or ZERO),
    )
    risks = [_item(fw, for_director) for fw in stock[:ITEMS_MAX]]

    counts = select(InventoryCount.day).order_by(InventoryCount.day.desc()).limit(1)
    if restaurant_id is not None:
        counts = counts.where(InventoryCount.restaurant_id == restaurant_id)
    last_count = session.execute(counts).scalar()

    place = places.get(restaurant_id) if restaurant_id else None
    return {
        "scope": "restaurant" if restaurant_id else "network",
        "restaurant": {"code": place.code, "name": place.name} if place else None,
        "week": f"{week.start:%d.%m.%Y}–{week.end:%d.%m.%Y}",
        "kpis": kpis,
        "kpis_previous_digest": (previous or {}).get("kpis"),
        "network_average": _kpis(snapshots.get(None)) if restaurant_id else None,
        "processes": processes,
        "problems": [_item(fw, for_director) for fw in problems],
        "opportunities": [_item(fw, for_director) for fw in opportunities],
        "on_table": {
            "losses": money(losses),
            "potential": money(potential),
            "total": money(losses + potential),
        },
        "improved": improved,
        "risks": risks,
        "last_count": f"{last_count:%d.%m.%Y}" if last_count else None,
        "restaurants_count": None if restaurant_id else len(places),
    }
