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

# Prices change only with a new menu (twice a year, the client's rule): until then, cost-side steps; the new
# price goes into the next menu's package.
ACTIONS = [
    "Запросить у поставщика цену ниже или найти другого поставщика",
    "Проверить техкарту: можно ли уменьшить порцию дорогого ингредиента или заменить его",
    "Заложить новую цену блюда в следующее меню",
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
        if price <= 0:  # free portions (staff meals, 100 % discounts): no food cost to speak of
            continue
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
                    f"В следующем меню цена {rub(new_price)} вместо {rub(price)} вернет фудкост к цели — "
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


ACTIONS_PLOWHORSE = [
    "Заложить небольшое повышение цены блюда в следующее меню",
    "Проверить техкарту: можно ли снизить себестоимость без потери вкуса (порция, гарнир, замена)",
]
ACTIONS_PUZZLE = [
    "Продвигать блюдо: рекомендация официантов, место в меню, фото, сет или блюдо дня",
    "Проверить, почему его берут редко: название, описание, цена, подача",
]


def detect_menu(facts: Facts, cfg: EngineParams = DEFAULT, covered: list[Draft] | None = None) -> list[Draft]:
    """Menu engineering: popularity × margin of each dish within its menu category (network-wide).

    - a popular dish with a low margin («рабочая лошадка»): a small price rise in the next menu;
    - a rarely ordered dish with a high margin («загадка»): promote it.
    Dishes whose food cost is already a finding (`covered`) are left to that finding."""
    if not facts.receipts or not facts.sales:
        return []
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    prices = unit_prices(facts, start, end)
    recipes = lines_on(facts.recipe_lines, end)
    taken = {d.evidence.get("menu_item") for d in covered or []}
    portions: dict[UUID, Decimal] = defaultdict(Decimal)
    for s in facts.sales:
        if start <= s.day <= end:
            portions[s.menu_item] += s.qty
    by_category: dict[str, list[tuple[UUID, Decimal, Decimal]]] = defaultdict(list)  # item, margin, portions
    for item, info in facts.menu.items():
        if not info.category or not info.price or info.price <= 0 or not portions[item]:
            continue
        cost = portion_cost(explode(item, Decimal(1), recipes) if item in recipes else {}, prices)
        if cost is None:
            continue
        by_category[info.category].append((item, info.price - cost, portions[item]))
    drafts: list[Draft] = []
    for category, dishes in sorted(by_category.items()):
        if len(dishes) < 2:
            continue
        total = sum((q for _, _, q in dishes), Decimal(0))
        avg = sum((m * q for _, m, q in dishes), Decimal(0)) / total
        fair = Decimal(1) / len(dishes)
        table = [
            {
                "menu_item": facts.menu[i].code,
                "name": facts.menu[i].name,
                "margin": str(m.quantize(Decimal("0.01"))),
                "share": str((q / total).quantize(Decimal("0.0001"))),
            }
            for i, m, q in dishes
        ]
        for item, margin, qty in dishes:
            info = facts.menu[item]
            if info.code in taken or avg <= 0:
                continue
            assert info.price is not None
            share = qty / total
            popular = share >= cfg.M2_ME_POPULARITY * fair
            evidence: dict[str, object] = {
                "menu_item": info.code,
                "category": category,
                "price": str(info.price.quantize(Decimal("0.01"))),
                "margin": str(margin.quantize(Decimal("0.01"))),
                "category_margin": str(avg.quantize(Decimal("0.01"))),
                "share": str(share.quantize(Decimal("0.0001"))),
                "fair_share": str(fair.quantize(Decimal("0.0001"))),
                "portions": str(qty.quantize(Decimal("0.001"))),
                "dishes": table,
            }
            if popular and margin < cfg.M2_ME_LOW_MARGIN * avg:
                new_price = suggested_price(info.price * (1 + cfg.M2_ME_PRICE_RISE), Decimal(1), cfg)
                effect = per_month((new_price - info.price) * qty * cfg.M2_KEEP, start, end)
                if effect < cfg.M2_MATERIALITY_RUB_MONTH:
                    continue
                drafts.append(
                    _menu_draft(
                        info.code,
                        f"Популярное, но мало зарабатывает: {info.name}",
                        f"«{info.name}» — {pct(share, 0)} продаж категории «{category}», блюдо берут чаще "
                        f"других, но с порции оно приносит {rub(margin)} при {rub(avg)} в среднем по "
                        f"категории. В следующем меню цена {rub(new_price)} вместо {rub(info.price)} — "
                        f"≈ {rub(effect)} в месяц по сети (консервативно)",
                        effect,
                        start,
                        end,
                        ACTIONS_PLOWHORSE,
                        {**evidence, "kind": "plowhorse", "new_price": str(new_price)},
                    )
                )
            elif not popular and margin > cfg.M2_ME_HIGH_MARGIN * avg:
                rest = [(m, q) for i, m, q in dishes if i != item]
                others = sum((m * q for m, q in rest), Decimal(0)) / sum((q for _, q in rest), Decimal(0))
                effect = per_month(qty * cfg.M2_ME_PROMO_GROWTH * (margin - others), start, end)
                if effect < cfg.M2_MATERIALITY_RUB_MONTH:
                    continue
                drafts.append(
                    _menu_draft(
                        info.code,
                        f"Выгодное, но редко берут: {info.name}",
                        f"«{info.name}» приносит {rub(margin)} с порции — больше, чем в среднем по "
                        f"категории «{category}» ({rub(avg)}), но блюдо берут редко: {pct(share, 0)} продаж "
                        f"категории. Если продвижение добавит блюду {pct(cfg.M2_ME_PROMO_GROWTH, 0)} продаж "
                        f"за счет других блюд категории — ≈ {rub(effect)} в месяц по сети",
                        effect,
                        start,
                        end,
                        ACTIONS_PUZZLE,
                        {
                            **evidence,
                            "kind": "puzzle",
                            "others_margin": str(others.quantize(Decimal("0.01"))),
                        },
                    )
                )
    return drafts


def _menu_draft(
    code: str,
    title: str,
    headline: str,
    effect: Decimal,
    start: date,
    end: date,
    actions: list[str],
    evidence: dict[str, object],
) -> Draft:
    return Draft(
        key=f"M2:net:{code}:{evidence['kind']}",
        module="M2",
        kind="opportunity",
        process="planning",
        restaurant=None,
        title=title,
        headline=headline,
        effect_rub_month=effect,
        effect_note=None,
        confidence="medium",
        period_from=start,
        period_to=end,
        actions=list(actions),
        evidence=evidence,
    )
