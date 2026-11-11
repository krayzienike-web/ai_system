"""№ 1. Before a stock count: what to count carefully (docs/07 «ИИ-агенты», ADR 0010).

The next count is expected the restaurant's usual interval (the median of the gaps between its counts) after
the last one; a missed one moves to the next cycle, as on the director's screen. From `LEAD_DAYS` before it,
the director gets a list of up to `MAX_ITEMS` products:
- products of the restaurant's open M1/M4 findings the director already sees (checked, with a task: ADR 0009);
- the largest differences in rubles at the last count (actual − books, × the restaurant's purchase price);
- the most valuable stock at the last count.
Only the restaurant's own numbers: nothing of other restaurants goes into a director's note.
«Создать задачу» makes a task with the list as its checklist, due on the day of the count.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from statistics import median
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.catalog.models import Product
from app.insights.models import Finding, FindingStatus
from app.operations.models import InventoryCount, Receipt
from app.tasks.models import Task
from app.tenancy.models import Restaurant

LEAD_DAYS = 2  # the note comes this many days before the expected count, and on the day itself
MAX_ITEMS = 12
TOP_DIFFS = 5
TOP_VALUE = 3
PRICE_DAYS = 90  # the purchase price: the restaurant's receipts of this long before the count
MODULES = ("M1", "M4")
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


@dataclass(frozen=True)
class Schedule:
    last: date
    typical_days: int
    expected: date


def schedule(days: list[date], today: date) -> Schedule | None:
    """The next count from the past ones: two counts at least, else there is no usual interval. A count that
    was due and did not happen moves to the next cycle — as «Следующая инвентаризация» on the director's
    screen shows it (`overview.service.context`)."""
    days = sorted(set(days))
    if len(days) < 2:
        return None
    gap = int(median((b - a).days for a, b in pairwise(days)))
    expected = days[-1] + timedelta(days=gap)
    while expected < today:
        expected += timedelta(days=gap)
    return Schedule(days[-1], gap, expected)


def count_days(session: Session) -> dict[UUID, list[date]]:
    out: dict[UUID, list[date]] = defaultdict(list)
    for rid, day in session.execute(
        select(InventoryCount.restaurant_id, InventoryCount.day).distinct().order_by(InventoryCount.day)
    ):
        out[rid].append(day)
    return out


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _qty(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.001")).normalize())


def _finding_products(key: str, codes: set[str]) -> list[str]:
    """Product codes of an engine finding's key: «M1:R01:P01[:under]», «M4:R11:P02-P03»."""
    parts = key.split(":")
    if len(parts) < 3 or parts[1] == "net":
        return []
    if parts[2] in codes:
        return [parts[2]]
    pair = parts[2].split("-")
    return pair if len(pair) == 2 and all(p in codes for p in pair) else []


def _seen_by_director(session: Session, restaurant_id: UUID) -> list[Finding]:
    """The restaurant's open M1/M4 findings as its director sees them: checked and with a task (ADR 0009) —
    the rule of the findings' row-level security (migration 0025), here under the system's scope."""
    tasked = exists().where(Task.finding_id == Finding.id, Task.restaurant_id == Finding.restaurant_id)
    rows = session.execute(
        select(Finding)
        .where(
            Finding.restaurant_id == restaurant_id,
            Finding.module.in_(MODULES),
            Finding.status.in_(OPEN),
            Finding.key.is_not(None),
            tasked,
        )
        .order_by(Finding.effect_rub_month.desc().nulls_last(), Finding.key)
    ).scalars()
    return [f for f in rows if f.checked]


def _prices(session: Session, restaurant_id: UUID, until: date) -> dict[UUID, Decimal]:
    """₽ per base unit: the restaurant's own receipts of `PRICE_DAYS` up to the count."""
    rows = session.execute(
        select(Receipt.product_id, func.sum(Receipt.amount), func.sum(Receipt.qty))
        .where(
            Receipt.restaurant_id == restaurant_id,
            Receipt.day > until - timedelta(days=PRICE_DAYS),
            Receipt.day <= until,
        )
        .group_by(Receipt.product_id)
    )
    return {pid: amount / qty for pid, amount, qty in rows if qty and qty > 0}


def prepare(session: Session, restaurant: Restaurant, count_on: date, today: date) -> NoteDraft | None:
    """The list for the count on `count_on` (expected or asked for), from the last count before it.
    None when there is no count to go by."""
    last = session.execute(
        select(func.max(InventoryCount.day)).where(
            InventoryCount.restaurant_id == restaurant.id, InventoryCount.day <= today
        )
    ).scalar()
    if last is None:
        return None
    products = {p.id: p for p in session.execute(select(Product)).scalars()}
    by_code = {p.code: p for p in products.values()}
    price = _prices(session, restaurant.id, last)
    counted = session.execute(
        select(InventoryCount).where(
            InventoryCount.restaurant_id == restaurant.id, InventoryCount.day == last
        )
    ).scalars()
    diffs: dict[UUID, Decimal] = {}
    values: dict[UUID, Decimal] = {}
    for c in counted:
        p = price.get(c.product_id)
        if p is None:
            continue
        values[c.product_id] = values.get(c.product_id, Decimal(0)) + c.actual_qty * p
        if c.book_qty is not None:
            diffs[c.product_id] = diffs.get(c.product_id, Decimal(0)) + (c.actual_qty - c.book_qty) * p

    chosen: dict[UUID, dict[str, object]] = {}

    def add(pid: UUID, reason: str, **extra: object) -> None:
        if pid in chosen or len(chosen) >= MAX_ITEMS:
            return
        prod = products[pid]
        chosen[pid] = {
            "code": prod.code,
            "name": prod.name,
            "unit": prod.base_unit,
            "reason": reason,
            **extra,
        }

    for f in _seen_by_director(session, restaurant.id):
        for code in _finding_products(f.key or "", set(by_code)):
            add(by_code[code].id, "finding", finding=f.title)
    for pid, diff in sorted(diffs.items(), key=lambda kv: (kv[1], products[kv[0]].code))[:TOP_DIFFS]:
        if diff < 0:  # a shortage: what the count is about
            add(pid, "shortage", diff_rub=_money(-diff))
    for pid, value in sorted(values.items(), key=lambda kv: (-kv[1], products[kv[0]].code))[:TOP_VALUE]:
        add(pid, "value", stock_rub=_money(value))
    if not chosen:
        return None
    return NoteDraft(
        agent=Agent.INVENTORY_PREP,
        audience=Audience.DIRECTOR,
        restaurant_id=restaurant.id,
        key=f"inventory_prep:{restaurant.code}:{count_on.isoformat()}",
        for_date=count_on,
        facts={
            "restaurant": restaurant.name,
            "count_on": count_on.isoformat(),
            "days_left": (count_on - today).days,
            "last_count": last.isoformat(),
            "products": list(chosen.values()),
        },
        proposal={
            "action": "create_task",
            "due_on": count_on.isoformat(),
            "title": f"Подготовка к инвентаризации {count_on.strftime('%d.%m')}",
        },
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    """The restaurants whose next count is expected within `LEAD_DAYS`."""
    out = []
    days = count_days(session)
    for r in restaurants:
        s = schedule([d for d in days.get(r.id, []) if d <= today], today)
        if s is None or (s.expected - today).days > LEAD_DAYS:
            continue
        if (d := prepare(session, r, s.expected, today)) is not None:
            out.append(d)
    return out
