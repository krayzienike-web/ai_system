"""M6. Stock outlook: will a product run out before the next delivery, or spoil before it is used
(docs/02-analytics-spec.md, M6; docs/12-analytics-engine.md).

For each restaurant and product, at the end of the restaurant's data:
1. Stock = the last count + receipts + transfers in − transfers out − write-offs − use since the count.
   Use = the recipes' usage × (1 + the restaurant's usual unexplained use of this product, from M1).
2. Daily need ahead = the same weekday's average use over the last `M6_HISTORY_DAYS` (seasonal-naive).
3. The next delivery = the next weekday on which this product has been delivered over that history.
4. Shortage: the stock runs out before the next delivery.
It is not a monthly loss: the finding says what is at risk (the dishes' revenue per day).
Overstock (stock that spoils before it is used) needs real stock snapshots: the computed stock drifts too far
from a count weeks ago — planned with the «Остатки на дату» export.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.analytics.drafts import Draft, dmy, rub
from app.analytics.facts import Facts
from app.analytics.m1 import M1Row
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.usage import Usage
from app.catalog.recipes import explode, lines_on

UNIT = {"kg": "кг", "l": "л", "pcs": "шт"}
IN_WEEKDAY = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]


@dataclass
class Outlook:
    restaurant: UUID
    product: UUID
    end: date  # the last day of the restaurant's data
    stock: Decimal  # at the end of that day
    need: list[Decimal]  # per weekday, Monday first
    loss: Decimal  # the usual unexplained use added to the recipes'
    next_delivery: date | None

    def zero_day(self, horizon: int) -> date | None:
        """The first day the stock does not cover that day's need."""
        left = self.stock
        for i in range(1, horizon + 1):
            day = self.end + timedelta(days=i)
            left -= self.need[day.weekday()]
            if left < 0:
                return day
        return None


def outlooks(facts: Facts, usage: Usage, m1_rows: list[M1Row], cfg: EngineParams = DEFAULT) -> list[Outlook]:
    if not facts.sales:
        return []
    data_end: dict[UUID, date] = {}
    for s in facts.sales:
        if s.restaurant not in data_end or s.day > data_end[s.restaurant]:
            data_end[s.restaurant] = s.day
    last_count: dict[tuple[UUID, UUID], tuple[date, Decimal]] = {}
    for c in facts.counts:
        key = (c.restaurant, c.product)
        if key not in last_count or c.day > last_count[key][0]:
            last_count[key] = (c.day, c.actual)
    loss: dict[tuple[UUID, UUID], Decimal] = {}
    for r in sorted(m1_rows, key=lambda r: r.end):
        loss[(r.restaurant, r.product)] = min(max(r.share, Decimal(0)), cfg.M6_MAX_LOSS)
    moves: dict[tuple[UUID, UUID], list[tuple[date, Decimal]]] = defaultdict(list)
    delivered: dict[tuple[UUID, UUID], list[date]] = defaultdict(list)
    for rc in facts.receipts:
        moves[(rc.restaurant, rc.product)].append((rc.day, rc.qty))
        if rc.qty > 0:
            delivered[(rc.restaurant, rc.product)].append(rc.day)
    for t in facts.transfers:
        moves[(t.receiver, t.product)].append((t.day, t.qty))
        moves[(t.sender, t.product)].append((t.day, -t.qty))
    for w in facts.write_offs:
        moves[(w.restaurant, w.product)].append((w.day, -w.qty))

    out = []
    for (restaurant, product), (counted_on, counted) in last_count.items():
        end = data_end.get(restaurant)
        info = facts.products.get(product)
        if end is None or end < counted_on or info is None or info.is_semi:
            continue
        key = (restaurant, product)
        extra = 1 + loss.get(key, Decimal(0))
        used = usage.total(restaurant, product, counted_on + timedelta(days=1), end) * extra
        stock = counted + sum((q for d, q in moves[key] if counted_on < d <= end), Decimal(0)) - used
        start = end - timedelta(days=cfg.M6_HISTORY_DAYS - 1)
        by_weekday: list[list[Decimal]] = [[] for _ in range(7)]
        daily = usage.by_day.get(key, {})
        for i in range(cfg.M6_HISTORY_DAYS):
            day = start + timedelta(days=i)
            by_weekday[day.weekday()].append(daily.get(day, Decimal(0)) * extra)
        need = [sum(v, Decimal(0)) / len(v) if v else Decimal(0) for v in by_weekday]
        if sum(need) <= 0:
            continue
        recent = [d for d in delivered[key] if start <= d <= end]
        weekdays = {d.weekday() for d in recent}
        next_delivery = next(
            (end + timedelta(days=i) for i in range(1, 8) if (end + timedelta(days=i)).weekday() in weekdays),
            None,
        )
        out.append(
            Outlook(
                restaurant,
                product,
                end,
                stock,
                need,
                extra - 1,
                next_delivery,
            )
        )
    return out


def detect(facts: Facts, usage: Usage, m1_rows: list[M1Row], cfg: EngineParams = DEFAULT) -> list[Draft]:
    drafts = []
    for o in outlooks(facts, usage, m1_rows, cfg):
        info = facts.products[o.product]
        code = facts.restaurants[o.restaurant]
        unit = UNIT.get(info.unit, info.unit)
        if o.next_delivery is not None and o.stock > 0:
            zero = o.zero_day((o.next_delivery - o.end).days)
            if zero is not None and zero < o.next_delivery:
                short = (o.next_delivery - zero).days
                at_risk = _revenue_per_day(facts, o, cfg)
                if short >= cfg.M6_SHORT_DAYS and at_risk >= cfg.M6_REVENUE_AT_RISK:
                    drafts.append(_shortage(facts, o, info.name, code, unit, zero, short, at_risk))
                    continue
    return drafts


def _revenue_per_day(facts: Facts, o: Outlook, cfg: EngineParams) -> Decimal:
    """Average daily revenue of the restaurant's dishes needing this product: what a stop-list would cost."""
    lines = lines_on(facts.recipe_lines, o.end)
    dishes = {item for item in facts.menu if explode(item, Decimal(1), lines).get(o.product, Decimal(0)) > 0}
    start = o.end - timedelta(days=cfg.M6_HISTORY_DAYS - 1)
    revenue = sum(
        (
            s.revenue
            for s in facts.sales
            if s.restaurant == o.restaurant and s.menu_item in dishes and start <= s.day <= o.end
        ),
        Decimal(0),
    )
    return (revenue / cfg.M6_HISTORY_DAYS).quantize(Decimal(1))


def _shortage(
    facts: Facts, o: Outlook, name: str, code: str, unit: str, zero: date, short: int, at_risk: Decimal
) -> Draft:
    assert o.next_delivery is not None
    return Draft(
        key=f"M6:{code}:{facts.products[o.product].code}:shortage",
        module="M6",
        kind="problem",
        process="planning",
        restaurant=o.restaurant,
        title=f"Закончится до поставки: {name}",
        headline=(
            f"По расчету {name.lower()} закончится {dmy(zero)}, а ближайшая поставка — в "
            f"{IN_WEEKDAY[o.next_delivery.weekday()]} {dmy(o.next_delivery)}: {short} дн. без товара. "
            f"Блюда с ним приносят ≈ {rub(at_risk)} в день"
        ),
        effect_rub_month=None,
        effect_note=f"под угрозой ≈ {rub(at_risk)} выручки в день",
        confidence="medium",
        period_from=o.end + timedelta(days=1),
        period_to=o.next_delivery,
        actions=[
            "Дозаказать до поставки или взять перемещением из соседнего ресторана",
            "Проверить остаток на полке",
        ],
        evidence={
            "kind": "shortage",
            "product": facts.products[o.product].code,
            "data_until": o.end.isoformat(),
            "stock": str(o.stock.quantize(Decimal("0.001"))),
            "need_by_weekday": [str(n.quantize(Decimal("0.001"))) for n in o.need],
            "loss": str(o.loss.quantize(Decimal("0.0001"))),
            "zero_day": zero.isoformat(),
            "next_delivery": o.next_delivery.isoformat(),
            "revenue_per_day": str(at_risk),
        },
    )
