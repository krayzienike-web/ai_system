"""№ 13. The result of a stock count (docs/07 «ИИ-агенты», ADR 0010; stage 12).

After a count is loaded, the agent compares what the restaurant used between its last two counts with what the
recipes and the write-offs explain — the engine's M1 formula (U = A − T − W) — and keeps what goes beyond the
allowance of the product's category (the HQ's norms): U − allowance × T, in rubles at the restaurant's own
purchase price.
- To the director: up to `MAX_ITEMS` largest such differences of the restaurant, each with what to look at
  first (no write-offs at all; the product left by transfers; an open finding with a task). A product the
  whole network overspends (an open, checked finding «Техкарта, вероятно, устарела») is the network's card,
  not the kitchen: it is named apart and not counted. «Создать задачу» — a task «Объяснить расхождения» with a
  point per product; the director writes the explanation in its result.
- To the HQ: one note about the network — every restaurant counted within `RESULT_DAYS`, the differences
  beyond the allowance per month now and at the count before, the costliest product; where they grew first.
Only the restaurant's own numbers go into a director's note; the HQ sees the restaurants side by side.
A note lives `RESULT_DAYS` after its count: then it expires by itself.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.analytics import m1
from app.analytics.costs import LOOKBACK_DAYS, CostBook
from app.analytics.facts import (
    CountRow,
    Facts,
    ProductInfo,
    ReceiptRow,
    SaleRow,
    TransferRow,
    WriteOffRow,
)
from app.analytics.usage import Usage
from app.catalog.models import Product, RecipeLine
from app.catalog.recipes import Line
from app.insights.models import Finding, FindingStatus
from app.norms.service import Norms, load_norms
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tasks.models import Task
from app.tenancy.models import Restaurant

RESULT_DAYS = 21  # a count's result is news this long: counts are weeks apart
MAX_ITEMS = 5
ITEM_MIN_RUB_MONTH = Decimal(3000)  # as M1's materiality: a smaller difference is not worth explaining
MONTH_DAYS = Decimal(30)
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


def _rub(v: Decimal) -> str:
    return str(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _qty(v: Decimal) -> str:
    return plain(v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Excess:
    """One product of one period between counts: what went beyond the recipes, the write-offs and the
    allowance."""

    product: UUID
    qty: Decimal  # base units beyond the allowance
    rub: Decimal  # at the restaurant's purchase price
    write_off: Decimal
    transferred_out: Decimal


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    items: list[Excess]  # beyond the allowance, the largest first

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def per_month(self, rub: Decimal) -> Decimal:
        return rub * MONTH_DAYS / self.days

    def month(self, skip: set[UUID]) -> Decimal:
        return self.per_month(sum((x.rub for x in self.items if x.product not in skip), Decimal(0)))


def _facts(session: Session, restaurant: UUID, since: date, until: date, days: list[date]) -> Facts:
    """The restaurant's own facts from `since` to `until` (its counts on `days`): the purchases a bit earlier
    for the price (`costs.LOOKBACK_DAYS`), the other restaurants' never (their price is not the
    director's)."""
    f = Facts()
    for p in session.execute(select(Product)).scalars():
        f.products[p.id] = ProductInfo(p.code, p.name, p.category, p.base_unit, p.shelf_life_days, p.is_semi)
    f.recipe_lines = [
        Line(parent, r.product_id, r.gross_qty, r.valid_from)
        for r in session.execute(select(RecipeLine).where(RecipeLine.valid_from <= until)).scalars()
        if (parent := r.menu_item_id or r.semi_product_id) is not None
    ]
    f.sales = [
        SaleRow(restaurant, d, i, q, Decimal(0))
        for d, i, q in session.execute(
            select(Sale.day, Sale.menu_item_id, Sale.qty).where(
                Sale.restaurant_id == restaurant, Sale.day > since, Sale.day <= until
            )
        ).all()
    ]
    f.receipts = [
        ReceiptRow(restaurant, d, p, s, q, a)
        for d, p, s, q, a in session.execute(
            select(Receipt.day, Receipt.product_id, Receipt.supplier_id, Receipt.qty, Receipt.amount).where(
                Receipt.restaurant_id == restaurant,
                Receipt.day > since - timedelta(days=LOOKBACK_DAYS),
                Receipt.day <= until,
            )
        ).all()
    ]
    f.transfers = [
        TransferRow(*row)
        for row in session.execute(
            select(
                Transfer.restaurant_id,
                Transfer.to_restaurant_id,
                Transfer.day,
                Transfer.product_id,
                Transfer.qty,
            ).where(
                (Transfer.restaurant_id == restaurant) | (Transfer.to_restaurant_id == restaurant),
                Transfer.day > since,
                Transfer.day <= until,
            )
        ).all()
    ]
    f.write_offs = [
        WriteOffRow(restaurant, d, p, q, c)
        for d, p, q, c in session.execute(
            select(WriteOff.day, WriteOff.product_id, WriteOff.qty, WriteOff.reason_code).where(
                WriteOff.restaurant_id == restaurant, WriteOff.day > since, WriteOff.day <= until
            )
        ).all()
    ]
    f.counts = [
        CountRow(restaurant, d, p, b, a)
        for d, p, b, a in session.execute(
            select(
                InventoryCount.day,
                InventoryCount.product_id,
                InventoryCount.book_qty,
                InventoryCount.actual_qty,
            ).where(InventoryCount.restaurant_id == restaurant, InventoryCount.day.in_(days))
        ).all()
    ]
    return f


def periods(session: Session, restaurant: UUID, days: list[date], norms: Norms) -> list[Period]:
    """The periods between consecutive `days` (counts of the restaurant), each with what went beyond the
    allowance. A period the engine does not judge (shorter than `M1_MIN_THEORY_DAYS`) has no items."""
    if len(days) < 2:
        return []
    facts = _facts(session, restaurant, days[0], days[-1], days)
    rows = m1.rows(facts, Usage(facts), CostBook(facts.receipts))
    out_by: dict[tuple[date, UUID], Decimal] = defaultdict(Decimal)
    for t in facts.transfers:
        if t.sender == restaurant:
            for a, b in pairwise(days):
                if a < t.day <= b:
                    out_by[(b, t.product)] += t.qty
    by_end: dict[date, list[Excess]] = defaultdict(list)
    for r in rows:
        if r.unit_cost is None:
            continue
        info = facts.products[r.product]
        tol = norms.loss_allowance(info.category) / 100
        qty = r.unexplained - tol * r.theory
        if qty <= 0:
            continue
        by_end[r.end].append(
            Excess(r.product, qty, qty * r.unit_cost, r.write_off, out_by[(r.end, r.product)])
        )
    return [
        Period(a, b, sorted(by_end[b], key=lambda x: (-x.rub, facts.products[x.product].code)))
        for a, b in pairwise(days)
    ]


def card_products(session: Session) -> dict[UUID, str]:
    """Products of open, checked findings «Техкарта, вероятно, устарела» (`M1:net:<code>`): the
    network's card."""
    by_code = {p.code: p for p in session.execute(select(Product)).scalars()}
    out = {}
    for f in session.execute(
        select(Finding).where(
            Finding.module == "M1", Finding.restaurant_id.is_(None), Finding.status.in_(OPEN)
        )
    ).scalars():
        code = (f.evidence or {}).get("product")
        if f.checked and (f.key or "").startswith("M1:net:") and code in by_code:
            out[by_code[code].id] = by_code[code].name
    return out


def _director_findings(session: Session, restaurant: UUID) -> dict[str, str]:
    """Product code → the title of the restaurant's open finding about it that the director sees
    (checked, with a task: ADR 0009)."""
    tasked = exists().where(Task.finding_id == Finding.id, Task.restaurant_id == Finding.restaurant_id)
    out: dict[str, str] = {}
    for f in session.execute(
        select(Finding)
        .where(Finding.restaurant_id == restaurant, Finding.status.in_(OPEN), tasked)
        .order_by(Finding.effect_rub_month.desc().nulls_last(), Finding.key)
    ).scalars():
        code = (f.evidence or {}).get("product")
        if f.checked and isinstance(code, str):
            out.setdefault(code, f.title)
    return out


def _director(
    session: Session, r: Restaurant, p: Period, cards: dict[UUID, str], products: dict[UUID, Product]
) -> NoteDraft | None:
    seen = _director_findings(session, r.id)
    items: list[dict[str, Any]] = []
    for x in p.items:
        if x.product in cards or p.per_month(x.rub) < ITEM_MIN_RUB_MONTH:
            continue
        prod = products[x.product]
        hints: list[dict[str, str]] = []
        if prod.code in seen:
            hints.append({"kind": "finding", "finding": seen[prod.code]})
        if x.write_off == 0:
            hints.append({"kind": "no_write_offs"})
        if x.transferred_out > 0:
            hints.append({"kind": "transfers_out", "qty": _qty(x.transferred_out)})
        items.append(
            {
                "code": prod.code,
                "name": prod.name,
                "unit": prod.base_unit,
                "qty": _qty(x.qty),
                "rub": _rub(x.rub),
                "hints": hints,
            }
        )
        if len(items) == MAX_ITEMS:
            break
    if not items:
        return None
    card = sorted({cards[x.product] for x in p.items if x.product in cards})
    until = p.end + timedelta(days=RESULT_DAYS)
    return NoteDraft(
        agent=Agent.COUNT_RESULT,
        audience=Audience.DIRECTOR,
        restaurant_id=r.id,
        key=f"count_result:{r.code}:{p.end.isoformat()}",
        for_date=p.end,
        facts={
            "restaurant": r.name,
            "count_on": p.end.isoformat(),
            "since": p.start.isoformat(),
            "total_rub": _rub(sum((Decimal(i["rub"]) for i in items), Decimal(0))),
            "products": items,
            "card_products": card,
        },
        proposal={
            "action": "create_task",
            "due_on": until.isoformat(),
            "title": f"Объяснить расхождения инвентаризации {p.end.strftime('%d.%m')}",
            "checklist": [f"Объяснить: {i['name']} — {i['rub']} ₽ сверх допуска" for i in items],
        },
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    days: dict[UUID, list[date]] = defaultdict(list)
    for rid, day in session.execute(
        select(InventoryCount.restaurant_id, InventoryCount.day)
        .where(InventoryCount.day <= today)
        .distinct()
        .order_by(InventoryCount.day)
    ):
        days[rid].append(day)
    fresh = [r for r in restaurants if days.get(r.id) and (today - days[r.id][-1]).days <= RESULT_DAYS]
    if not fresh:
        return []
    norms = load_norms(session)
    cards = card_products(session)
    products = {p.id: p for p in session.execute(select(Product)).scalars()}
    out = []
    network: list[dict[str, Any]] = []
    for r in fresh:
        ps = periods(session, r.id, days[r.id][-3:], norms)
        if not ps:
            continue
        last = ps[-1]
        if (d := _director(session, r, last, cards, products)) is not None:
            out.append(d)
        before = ps[-2] if len(ps) > 1 else None
        now_month = last.month(set(cards))
        before_month = before.month(set(cards)) if before else None
        top = next((x for x in last.items if x.product not in cards), None)
        network.append(
            {
                "restaurant": r.name,
                "code": r.code,
                "count_on": last.end.isoformat(),
                "month": _rub(now_month),
                "before": _rub(before_month) if before_month is not None else None,
                "grew": before_month is not None and now_month - before_month >= ITEM_MIN_RUB_MONTH,
                "top": products[top.product].name if top else None,
                "top_rub": _rub(top.rub) if top else None,
            }
        )
    over = [x for x in network if Decimal(x["month"]) >= ITEM_MIN_RUB_MONTH or x["grew"]]
    if over:
        over.sort(
            key=lambda x: (
                not x["grew"],
                -(Decimal(x["month"]) - Decimal(x["before"] or 0)) if x["grew"] else -Decimal(x["month"]),
                x["code"],
            )
        )
        latest = max(x["count_on"] for x in network)
        out.append(
            NoteDraft(
                agent=Agent.COUNT_RESULT,
                audience=Audience.HQ,
                restaurant_id=None,
                key=f"count_result:net:{latest}",
                for_date=date.fromisoformat(latest),
                facts={
                    "restaurants": over,
                    "counted": len(network),
                    "within": len(network) - len(over),
                    "grew": sum(1 for x in over if x["grew"]),
                    "card_products": sorted(set(cards.values())),
                },
            )
        )
    return out
