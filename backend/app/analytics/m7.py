"""M7. Data quality: what makes the other modules see wrong numbers (docs/12-analytics-engine.md, M7).

- A dish sells without a recipe: its products are used, but no recipe says so — they show up as losses.
- A restaurant's export stopped: the other restaurants have newer days, this one has a gap much longer than
  its usual pause between days with data.
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
        if not recent:
            continue  # sold without a recipe only in the past: the recipe exists now
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
