"""M5. Write-offs: a restaurant throws away much more of a product than the rest of the network, or always on
the same days of the week (docs/12-analytics-engine.md, M5).

Over the last `M5_WINDOW_DAYS` of a restaurant's data, per product:
- the write-off rate = written off / bought; the network's rate is the median of the other restaurants;
- the weekday pattern: the share of write-offs (in rubles) on the two neighbouring days of the week that hold
  the most of them, and in how many of the window's weeks that pattern repeats.
One finding per restaurant and product (`M5:<restaurant>:<product>`): the weekday pattern when it holds — it
says what to change in ordering — otherwise the rate against the network.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from uuid import UUID

from app.analytics.costs import CostBook
from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts, ProductInfo
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.usage import Usage

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
IN_WEEKDAY = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
ACTIONS_RATE = [
    "Заказывать меньшими партиями, чаще",
    "Проверить условия хранения и правило «первым пришел — первым ушел»",
]
ACTIONS_WEEKDAYS = ["Заказывать по дням недели под продажи, а не одинаково на все дни"]


@dataclass
class Spoilage:
    restaurant: UUID
    product: UUID
    bought: Decimal = Decimal(0)
    receipts: int = 0
    written: Decimal = Decimal(0)
    rub: Decimal = Decimal(0)
    by_day: dict[date, Decimal] = field(default_factory=lambda: defaultdict(Decimal))  # rubles

    @property
    def rate(self) -> Decimal | None:
        return self.written / self.bought if self.bought > 0 else None


def window(facts: Facts, cfg: EngineParams = DEFAULT) -> tuple[date, date] | None:
    if not facts.write_offs:
        return None
    end = max(s.day for s in facts.sales) if facts.sales else max(w.day for w in facts.write_offs)
    return end - timedelta(days=cfg.M5_WINDOW_DAYS - 1), end


def spoilage(facts: Facts, costs: CostBook, start: date, end: date) -> dict[tuple[UUID, UUID], Spoilage]:
    out: dict[tuple[UUID, UUID], Spoilage] = {}
    for r in facts.receipts:
        if start <= r.day <= end and r.qty > 0:
            s = out.setdefault((r.restaurant, r.product), Spoilage(r.restaurant, r.product))
            s.bought += r.qty
            s.receipts += 1
    for w in facts.write_offs:
        if start <= w.day <= end and w.qty > 0:
            s = out.setdefault((w.restaurant, w.product), Spoilage(w.restaurant, w.product))
            cost = costs.cost(w.restaurant, w.product, start, end)
            s.written += w.qty
            if cost is not None:
                value = w.qty * cost.rub_per_unit
                s.rub += value
                s.by_day[w.day] += value
    return out


def weekday_pattern(s: Spoilage, start: date, end: date) -> tuple[int, Decimal, int, int] | None:
    """The two neighbouring weekdays with the most write-offs: (first weekday, their share, weeks where they
    hold most of that week's write-offs, weeks with write-offs)."""
    if s.rub <= 0:
        return None
    by_weekday = [Decimal(0)] * 7
    for day, value in s.by_day.items():
        by_weekday[day.weekday()] += value
    first = max(range(7), key=lambda d: by_weekday[d] + by_weekday[(d + 1) % 7])
    share = (by_weekday[first] + by_weekday[(first + 1) % 7]) / s.rub
    weeks: dict[int, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for day, value in s.by_day.items():
        week = (day - start).days // 7
        weeks[week][1] += value
        if day.weekday() in (first, (first + 1) % 7):
            weeks[week][0] += value
    held = sum(1 for pair, total in weeks.values() if total > 0 and pair / total >= Decimal("0.5"))
    return first, share, held, len(weeks)


def detect(facts: Facts, usage: Usage, costs: CostBook, cfg: EngineParams = DEFAULT) -> list[Draft]:
    span = window(facts, cfg)
    if span is None:
        return []
    start, end = span
    rows = spoilage(facts, costs, start, end)
    by_product: dict[UUID, list[Spoilage]] = defaultdict(list)
    for s in rows.values():
        if s.rate is not None:
            by_product[s.product].append(s)
    drafts = []
    for s in rows.values():
        if s.rub <= 0 or s.rate is None:
            continue
        info = facts.products[s.product]
        code = facts.restaurants[s.restaurant]
        pattern = weekday_pattern(s, start, end)
        if pattern is not None:
            first, share, held, weeks = pattern
            excess = s.rub * (share - Decimal(2) / 7)
            effect = per_month(excess, start, end)
            if (
                share >= cfg.M5_WEEKDAY_SHARE
                and held >= cfg.M5_WEEKDAY_WEEKS
                and effect >= cfg.M5_WEEKDAY_MATERIALITY_RUB_MONTH
            ):
                drafts.append(_weekdays(facts, s, info, code, first, share, held, weeks, effect, start, end))
                continue
        others = [
            o.rate for o in by_product[s.product] if o.restaurant != s.restaurant and o.rate is not None
        ]
        if len(others) < 2:
            continue
        typical = Decimal(median(others))
        if s.rate < cfg.M5_TIMES * typical or s.rate - typical < cfg.M5_EXCESS:
            continue
        effect = per_month(s.rub * (1 - typical / s.rate), start, end)
        if effect < cfg.M5_MATERIALITY_RUB_MONTH:
            continue
        drafts.append(_rate(facts, usage, s, info, code, typical, effect, start, end))
    return drafts


def _cover_days(usage: Usage, s: Spoilage, start: date, end: date) -> Decimal | None:
    """How many days of use one delivery holds on average."""
    used = usage.total(s.restaurant, s.product, start, end)
    days = (end - start).days + 1
    if used <= 0 or not s.receipts:
        return None
    return (s.bought / s.receipts) / (used / days)


def _rate(
    facts: Facts,
    usage: Usage,
    s: Spoilage,
    info: ProductInfo,
    code: str,
    typical: Decimal,
    effect: Decimal,
    start: date,
    end: date,
) -> Draft:
    assert s.rate is not None
    factor = s.rate / typical if typical > 0 else None
    cover = _cover_days(usage, s, start, end)
    stale = cover is not None and info.shelf_life_days is not None and cover > info.shelf_life_days
    how_much = (
        f"в {str(factor.quantize(Decimal('0.1'))).replace('.', ',')} раза больше" if factor else "больше"
    )
    return Draft(
        key=f"M5:{code}:{info.code}",
        module="M5",
        kind="problem",
        process="writeoffs",
        restaurant=s.restaurant,
        title=f"Списания выше сети: {info.name}",
        headline=(
            f"За {dmy(start)}–{dmy(end)} списано {pct(s.rate)} закупленного — {how_much}, чем в среднем по "
            f"сети ({pct(typical)})"
            + (
                f". Одна поставка — на {cover.quantize(Decimal(1))} дн. при сроке годности "
                f"{info.shelf_life_days} дн."
                if stale and cover is not None
                else ""
            )
            + f". Потери ≈ {rub(effect)} в месяц"
        ),
        effect_rub_month=effect,
        effect_note=None,
        confidence="high" if s.receipts >= 4 else "medium",
        period_from=start,
        period_to=end,
        actions=(["Заказывать партиями не больше срока годности"] if stale else []) + list(ACTIONS_RATE),
        evidence={
            "kind": "rate",
            "product": info.code,
            "bought": str(s.bought.quantize(Decimal("0.001"))),
            "written": str(s.written.quantize(Decimal("0.001"))),
            "written_rub": str(s.rub.quantize(Decimal("0.01"))),
            "rate": str(s.rate.quantize(Decimal("0.0001"))),
            "network_rate": str(typical.quantize(Decimal("0.0001"))),
            "receipts": s.receipts,
            "cover_days": None if cover is None else str(cover.quantize(Decimal("0.1"))),
            "shelf_life_days": info.shelf_life_days,
        },
    )


def _weekdays(
    facts: Facts,
    s: Spoilage,
    info: ProductInfo,
    code: str,
    first: int,
    share: Decimal,
    held: int,
    weeks: int,
    effect: Decimal,
    start: date,
    end: date,
) -> Draft:
    days = f"{IN_WEEKDAY[first]} и {IN_WEEKDAY[(first + 1) % 7]}"
    sold = _sales_by_weekday(facts, s.restaurant, start, end)
    slow = (
        sold is not None
        and sold[first] + sold[(first + 1) % 7] < 2 * sum(sold) / 7
        and _even_orders(facts, s, start, end)
    )
    return Draft(
        key=f"M5:{code}:{info.code}",
        module="M5",
        kind="problem",
        process="writeoffs",
        restaurant=s.restaurant,
        title=f"Списания в {days}: {info.name}",
        headline=(
            f"{pct(share, 0)} списаний за {dmy(start)}–{dmy(end)} — в {days}, так {held} недели из {weeks}"
            + (". Заказ одинаковый на все дни, а продажи в эти дни ниже" if slow else "")
            + f". Потери ≈ {rub(effect)} в месяц"
        ),
        effect_rub_month=effect,
        effect_note=None,
        confidence="high" if held == weeks else "medium",
        period_from=start,
        period_to=end,
        actions=list(ACTIONS_WEEKDAYS) + ACTIONS_RATE[1:],
        evidence={
            "kind": "weekdays",
            "product": info.code,
            "weekdays": [WEEKDAYS[first], WEEKDAYS[(first + 1) % 7]],
            "first_weekday": first,
            "share": str(share.quantize(Decimal("0.0001"))),
            "weeks_held": held,
            "weeks": weeks,
            "written_rub": str(s.rub.quantize(Decimal("0.01"))),
            "by_weekday": _by_weekday(s),
        },
    )


def _by_weekday(s: Spoilage) -> list[str]:
    out = [Decimal(0)] * 7
    for day, value in s.by_day.items():
        out[day.weekday()] += value
    return [str(v.quantize(Decimal("0.01"))) for v in out]


def _sales_by_weekday(facts: Facts, restaurant: UUID, start: date, end: date) -> list[Decimal] | None:
    out = [Decimal(0)] * 7
    for sale in facts.sales:
        if sale.restaurant == restaurant and start <= sale.day <= end:
            out[sale.day.weekday()] += sale.revenue
    return out if sum(out) > 0 else None


def _even_orders(facts: Facts, s: Spoilage, start: date, end: date) -> bool:
    """Delivered on most days, in about the same amount: the order does not follow the day of the week."""
    by_weekday: dict[int, list[Decimal]] = defaultdict(list)
    for r in facts.receipts:
        if r.restaurant == s.restaurant and r.product == s.product and start <= r.day <= end:
            by_weekday[r.day.weekday()].append(r.qty)
    if len(by_weekday) < 5:
        return False
    means = [sum(v, Decimal(0)) / len(v) for v in by_weekday.values()]
    return max(means) <= min(means) * Decimal("1.15")
