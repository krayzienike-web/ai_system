"""M7. Data quality: what makes the other modules see wrong numbers (docs/12-analytics-engine.md, M7).

- A dish sells without a recipe: its products are used, but no recipe says so — they show up as losses.
- A restaurant's export stopped: the other restaurants have newer days, this one has a gap much longer than
  its usual pause between days with data.
- The books go below zero between counts: more was used than there was and came in — a document is missing.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from statistics import median
from uuid import UUID

from app.analytics.drafts import Draft, dmy, pct
from app.analytics.facts import Facts
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.usage import Usage

SOURCES = {
    # kind of facts -> (title, «нет ...», what is not checked meanwhile, action)
    "sales": (
        "Продажи из r_keeper загружены только по",
        "Продаж нет",
        "расход по техкартам и фудкост за это время не посчитаны",
        "Загрузить продажи за пропущенные дни",
    ),
    "receipts": (
        "Закупки из 1С:ERP загружены только по",
        "Закупок нет",
        "цены и приходы за это время не проверены",
        "Загрузить закупки за пропущенные дни",
    ),
}


def detect(facts: Facts, cfg: EngineParams = DEFAULT) -> list[Draft]:
    return _no_recipe(facts, cfg) + _gaps(facts, cfg)


def _has_recipe(facts: Facts) -> dict[UUID, date]:
    """Menu item -> the first day a recipe of it is valid."""
    first: dict[UUID, date] = {}
    for line in facts.recipe_lines:
        if line.parent_id not in first or line.valid_from < first[line.parent_id]:
            first[line.parent_id] = line.valid_from
    return first


def _no_recipe(facts: Facts, cfg: EngineParams) -> list[Draft]:
    if not facts.sales:
        return []
    end = max(s.day for s in facts.sales)
    start = end - timedelta(days=cfg.M7_WINDOW_DAYS - 1)
    recipe_from = _has_recipe(facts)
    revenue = sum((s.revenue for s in facts.sales if start <= s.day <= end), Decimal(0))
    without: dict[UUID, list[tuple[date, UUID, Decimal, Decimal]]] = defaultdict(list)
    for s in facts.sales:
        valid = recipe_from.get(s.menu_item)
        if valid is None or s.day < valid:
            without[s.menu_item].append((s.day, s.restaurant, s.qty, s.revenue))
    drafts = []
    for item, sold in without.items():
        recent = [x for x in sold if start <= x[0] <= end]
        valid_from = recipe_from.get(item)
        if not recent or (valid_from is not None and valid_from <= end):
            continue  # the recipe exists now: fixed, nothing to do
        info = facts.menu[item]
        since = min(x[0] for x in sold)
        share = sum((x[3] for x in recent), Decimal(0)) / revenue if revenue else Decimal(0)
        places = sorted({facts.restaurants[x[1]] for x in recent})
        drafts.append(
            Draft(
                key=f"M7:net:{info.code}",
                module="M7",
                kind="problem",
                process="accounting",
                restaurant=None,
                title=f"«{info.name}» продается без техкарты",
                headline=(
                    f"С {dmy(since)} блюдо продается без техкарты: {pct(share)} выручки сети за последние "
                    f"{cfg.M7_WINDOW_DAYS} дней, в {len(places)} ресторанах. Расход продуктов на него "
                    "система не видит — они попадают в потери"
                ),
                effect_rub_month=None,
                effect_note="фудкост и потери сети считаются неточно",
                confidence="high",
                period_from=since,
                period_to=end,
                actions=[f"Завести техкарту «{info.name}» в iiko и загрузить ее"],
                evidence={
                    "kind": "no_recipe",
                    "menu_item": info.code,
                    "since": since.isoformat(),
                    "window": [start.isoformat(), end.isoformat()],
                    "portions": str(sum((x[2] for x in recent), Decimal(0))),
                    "revenue_share": str(share.quantize(Decimal("0.0001"))),
                    "restaurants": places,
                },
            )
        )
    return drafts


def _gaps(facts: Facts, cfg: EngineParams) -> list[Draft]:
    days_of = {
        "sales": [(s.restaurant, s.day) for s in facts.sales],
        "receipts": [(r.restaurant, r.day) for r in facts.receipts],
    }
    drafts = []
    for source, pairs in days_of.items():
        if not pairs:
            continue
        network_end = max(d for _, d in pairs)
        by_restaurant: dict[UUID, set[date]] = defaultdict(set)
        for restaurant, day in pairs:
            by_restaurant[restaurant].add(day)
        title, none, unchecked, action = SOURCES[source]
        for restaurant, days in by_restaurant.items():
            last = max(days)
            gap = (network_end - last).days
            history = sorted(d for d in days if d > last - timedelta(days=cfg.M7_HISTORY_DAYS))
            pauses = [(b - a).days for a, b in pairwise(history)]
            usual = Decimal(median(pauses)) if pauses else Decimal(1)
            if gap < cfg.M7_GAP_DAYS or gap <= cfg.M7_GAP_TIMES * usual:
                continue
            code = facts.restaurants[restaurant]
            drafts.append(
                Draft(
                    key=f"M7:{code}:{source}",
                    module="M7",
                    kind="problem",
                    process="accounting",
                    restaurant=restaurant,
                    title=f"{title} {last:%d.%m}",
                    headline=(
                        f"{none} за последние {gap} дней, другие рестораны загрузили по "
                        f"{network_end:%d.%m} — {unchecked}"
                    ),
                    effect_rub_month=None,
                    effect_note=unchecked,
                    confidence="high",
                    period_from=last + timedelta(days=1),
                    period_to=network_end,
                    actions=[action],
                    evidence={
                        "kind": "gap",
                        "source": source,
                        "last": last.isoformat(),
                        "network_last": network_end.isoformat(),
                        "gap_days": gap,
                        "usual_pause_days": str(usual),
                    },
                )
            )
    return drafts


def detect_negative_stock(facts: Facts, usage: Usage, cfg: EngineParams = DEFAULT) -> list[Draft]:
    """Between two counts the books cannot go below zero: if receipts and transfers do not cover what the
    recipes used, a document is missing (most often an invoice). The latest such period per restaurant and
    product."""
    counts: dict[tuple[UUID, UUID], list[tuple[date, Decimal]]] = defaultdict(list)
    for c in facts.counts:
        counts[(c.restaurant, c.product)].append((c.day, c.actual))
    moves: dict[tuple[UUID, UUID], dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for r in facts.receipts:
        moves[(r.restaurant, r.product)][r.day] += r.qty
    for t in facts.transfers:
        moves[(t.receiver, t.product)][t.day] += t.qty
        moves[(t.sender, t.product)][t.day] -= t.qty
    for w in facts.write_offs:
        moves[(w.restaurant, w.product)][w.day] -= w.qty
    data_end: dict[UUID, date] = {}
    for s in facts.sales:
        data_end[s.restaurant] = max(data_end.get(s.restaurant, s.day), s.day)
    last_receipt: dict[UUID, date] = {}
    for r in facts.receipts:
        last_receipt[r.restaurant] = max(last_receipt.get(r.restaurant, r.day), r.day)
    drafts = []
    for (restaurant, product), series in counts.items():
        info = facts.products.get(product)
        if info is None or info.is_semi or restaurant not in data_end:
            continue
        series.sort()
        bounds = [
            (day, qty, series[i + 1][0] if i + 1 < len(series) else data_end[restaurant])
            for i, (day, qty) in enumerate(series)
        ]
        used = usage.by_day.get((restaurant, product), {})
        found = None
        for start, opening, end in reversed(bounds):
            if end <= start:
                continue
            days = (end - start).days
            daily = sum((q for d, q in used.items() if start < d <= end), Decimal(0)) / days
            limit = -cfg.M7_NEGATIVE_DAYS * daily
            stock, lowest, first_negative = opening, opening, None
            for i in range(1, days + 1):
                day = start + timedelta(days=i)
                stock += moves[(restaurant, product)].get(day, Decimal(0)) - used.get(day, Decimal(0))
                lowest = min(lowest, stock)
                if stock < limit and first_negative is None:
                    first_negative = day  # the day the books fell beyond what rounding could explain
            if daily > 0 and lowest < limit:
                found = (start, end, lowest, first_negative, daily)
                break
        if found is None:
            continue
        start, end, lowest, first_negative, daily = found
        assert first_negative is not None
        if restaurant in last_receipt and first_negative > last_receipt[restaurant]:
            continue  # after the restaurant's last invoice at all: the missing export, a finding of its own
        code = facts.restaurants[restaurant]
        unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)
        missing = str((-lowest).quantize(Decimal("0.1"))).replace(".", ",")
        drafts.append(
            Draft(
                key=f"M7:{code}:{info.code}:negative",
                module="M7",
                kind="problem",
                process="accounting",
                restaurant=restaurant,
                title=f"Расчетный остаток уходит в минус: {info.name}",
                headline=(
                    f"С {dmy(first_negative)} по документам израсходовано больше, чем было и пришло: "
                    f"до −{missing} {unit} (≈ {(-lowest / daily).quantize(Decimal(1))} дн. расхода). "
                    "Вероятно, не загружена "
                    "накладная или перемещение — потери и цены по товару считаются неверно"
                ),
                effect_rub_month=None,
                effect_note="расход и потери товара искажены",
                confidence="high",
                period_from=start + timedelta(days=1),
                period_to=end,
                actions=["Найти и загрузить недостающие накладные или перемещения за эти дни"],
                evidence={
                    "kind": "negative",
                    "product": info.code,
                    "from_count": start.isoformat(),
                    "to": end.isoformat(),
                    "first_negative": first_negative.isoformat(),
                    "lowest": str(lowest.quantize(Decimal("0.001"))),
                    "daily_use": str(daily.quantize(Decimal("0.001"))),
                },
            )
        )
    return drafts
