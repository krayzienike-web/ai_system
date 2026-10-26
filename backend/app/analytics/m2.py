"""M2. Food cost of dishes: which dishes cost more to make than the network's target allows.

A dish's food cost = cost of a portion at current purchase prices / menu price. Prices of ingredients are
the network's (weighted) purchase prices of the last 4 weeks: menu prices are set for the whole network, so
the finding is network-wide (HQ). The cause is named by comparing with the same window a quarter earlier.
See docs/12-analytics-engine.md (M2).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from app.analytics.drafts import Draft, pct, per_month, rub
from app.analytics.facts import Facts
from app.analytics.params import DEFAULT, EngineParams
from app.catalog.recipes import explode, lines_on
from app.norms.service import Norms

ACTIONS = [
    "Пересмотреть цену блюда в меню",
    "Проверить техкарту: можно ли уменьшить порцию дорогого ингредиента или заменить его",
    "Запросить у поставщика цену ниже или найти другого поставщика",
]


def unit_prices(facts: Facts, start: date, end: date) -> dict[UUID, Decimal]:
    """The network's weighted purchase price of each product over start..end."""
    totals: dict[UUID, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for r in facts.receipts:
        if start <= r.day <= end and r.qty > 0:
            totals[r.product][0] += r.amount
            totals[r.product][1] += r.qty
    return {p: amount / qty for p, (amount, qty) in totals.items() if qty > 0}


def portion_cost(need: dict[UUID, Decimal], prices: dict[UUID, Decimal]) -> Decimal | None:
    if not need or any(p not in prices for p in need):
        return None
    return sum((q * prices[p] for p, q in need.items()), Decimal(0))


def suggested_price(cost: Decimal, target: Decimal, cfg: EngineParams = DEFAULT) -> Decimal:
    step = cfg.M2_PRICE_STEP
    return (cost / target / step).to_integral_value(rounding=ROUND_CEILING) * step


def detect(facts: Facts, norms: Norms, cfg: EngineParams = DEFAULT) -> list[Draft]:
    if not facts.receipts:
        return []
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    before_end = end - timedelta(days=cfg.M2_COMPARE_DAYS)
    before_start = before_end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    now, before = unit_prices(facts, start, end), unit_prices(facts, before_start, before_end)
    recipes_now, recipes_before = lines_on(facts.recipe_lines, end), lines_on(facts.recipe_lines, before_end)
    revenue: dict[UUID, Decimal] = defaultdict(Decimal)
    portions: dict[UUID, Decimal] = defaultdict(Decimal)
    for s in facts.sales:
        if start <= s.day <= end:
            revenue[s.menu_item] += s.revenue
            portions[s.menu_item] += s.qty

    drafts: list[Draft] = []
    for item, info in facts.menu.items():
        need = explode(item, Decimal(1), recipes_now) if item in recipes_now else {}
        cost = portion_cost(need, now)
        if cost is None or not portions[item]:
            continue
        price = info.price or revenue[item] / portions[item]
        food_cost = cost / price
        target = norms.food_cost_target(info.category) / 100
        if food_cost <= target:
            continue
        potential = per_month((food_cost - target) * revenue[item] * cfg.M2_KEEP, start, end)
        if potential < cfg.M2_MATERIALITY_RUB_MONTH:
            continue
        need_before = explode(item, Decimal(1), recipes_before) if item in recipes_before else {}
        cost_before = portion_cost(need_before, before)
        drivers = sorted(
            ((now[p] * q - before[p] * need_before.get(p, q), p) for p, q in need.items() if p in before),
            key=lambda x: -x[0],
        )
        cause = ""
        if cost_before is not None and cost > cost_before and drivers and drivers[0][0] > 0:
            top = drivers[0][1]
            growth = now[top] / before[top] - 1
            cause = (
                f": себестоимость порции выросла с {rub(cost_before)} до {rub(cost)} "
                f"({facts.products[top].name.lower()}: +{pct(growth, 0)} к цене закупки), "
                "а цена в меню прежняя"
            )
        new_price = suggested_price(cost, target, cfg)
        drafts.append(
            Draft(
                key=f"M2:net:{info.code}",
                module="M2",
                kind="opportunity",
                process="planning",
                restaurant=None,
                title=f"Фудкост выше целевого: {info.name}",
                headline=(
                    f"Фудкост «{info.name}» — {pct(food_cost)} при цели {pct(target, 0)}{cause}. "
                    f"Цена {rub(new_price)} вместо {rub(price)} вернет фудкост к цели — "
                    f"≈ {rub(potential)} в месяц по сети (консервативно)"
                ),
                effect_rub_month=potential,
                effect_note=None,
                confidence="high" if cost_before is not None else "medium",
                period_from=start,
                period_to=end,
                actions=list(ACTIONS),
                evidence={
                    "menu_item": info.code,
                    "price": str(price.quantize(Decimal("0.01"))),
                    "cost": str(cost.quantize(Decimal("0.01"))),
                    "cost_before": None
                    if cost_before is None
                    else str(cost_before.quantize(Decimal("0.01"))),
                    "food_cost": str(food_cost.quantize(Decimal("0.0001"))),
                    "target": str(target),
                    "revenue": str(revenue[item].quantize(Decimal("0.01"))),
                    "suggested_price": str(new_price),
                    "before": [before_start.isoformat(), before_end.isoformat()],
                    "ingredients": [
                        {
                            "product": facts.products[p].code,
                            "qty": str(q.quantize(Decimal("0.0001"))),
                            "price": str(now[p].quantize(Decimal("0.01"))),
                            "price_before": None
                            if p not in before
                            else str(before[p].quantize(Decimal("0.01"))),
                        }
                        for p, q in need.items()
                    ],
                },
            )
        )
    return drafts
