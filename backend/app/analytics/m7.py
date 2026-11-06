"""M7. Data quality: what makes the other modules see wrong numbers (docs/12-analytics-engine.md, M7).

- A dish sells without a recipe: its products are used, but no recipe says so — they show up as losses.
- A restaurant's export stopped: the other restaurants have newer days, this one has a gap much longer than
  its usual pause between days with data.
- The books go below zero between counts: more was used than there was and came in — a document is missing.
- Invoice lines with no price or a price many times off the network's typical (a price per gram, a typo):
  costs, prices and food cost read them as they are (stage 6.5).
- The latest count without products the restaurant usually counts: until a full count their losses cannot
  be computed (stage 6.5).
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
    return _no_recipe(facts, cfg) + _gaps(facts, cfg) + _prices(facts, cfg) + _partial_counts(facts, cfg)


def _prices(facts: Facts, cfg: EngineParams) -> list[Draft]:
    """Invoice lines of the last weeks with no amount or a price far off the network's typical one."""
    if not facts.receipts:
        return []
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M7_WINDOW_DAYS - 1)
    history_start = end - timedelta(days=cfg.M7_HISTORY_DAYS - 1)
    prices: dict[UUID, list[Decimal]] = defaultdict(list)
    for r in facts.receipts:
        if history_start <= r.day <= end and r.qty > 0 and r.amount > 0:
            prices[r.product].append(r.amount / r.qty)
    typical = {p: Decimal(median(v)) for p, v in prices.items() if len(v) >= 3}
    odd: dict[UUID, list[dict[str, str]]] = defaultdict(list)
    for r in sorted(facts.receipts, key=lambda r: (r.day, str(r.product))):
        if not (start <= r.day <= end) or r.qty <= 0 or r.product not in typical:
            continue
        info = facts.products.get(r.product)
        if info is None:
            continue
        price, usual = r.amount / r.qty, typical[r.product]
        if price <= 0:
            why = "нет суммы"
        elif price * cfg.M7_PRICE_TIMES < usual:
            why = f"в {(usual / price).quantize(Decimal(1))} раз дешевле обычной"
        elif price > usual * cfg.M7_PRICE_TIMES:
            why = f"в {(price / usual).quantize(Decimal(1))} раз дороже обычной"
        else:
            continue
        odd[r.restaurant].append(
            {
                "day": r.day.isoformat(),
                "product": info.code,
                "name": info.name,
                "qty": str(r.qty.quantize(Decimal("0.001"))),
                "amount": str(r.amount.quantize(Decimal("0.01"))),
                "price": str(price.quantize(Decimal("0.01"))),
                "typical": str(usual.quantize(Decimal("0.01"))),
                "why": why,
                "unit": {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit),
            }
        )
    drafts = []
    for restaurant, lines in odd.items():
        code = facts.restaurants[restaurant]
        products = sorted({x["product"] for x in lines})
        first = lines[0]
        more = f" и еще {len(lines) - 1}" if len(lines) > 1 else ""
        drafts.append(
            Draft(
                key=f"M7:{code}:prices:{'-'.join(products)}",
                module="M7",
                kind="problem",
                process="accounting",
                restaurant=restaurant,
                title=f"Цены в накладных похожи на ошибку: {len(lines)} {_lines(len(lines))}",
                headline=(
                    f"{dmy(date.fromisoformat(first['day']))} «{first['name']}»: "
                    f"{_money(first['price'])}\u00a0₽ за "
                    f"{first['unit']} — {first['why']} ({_money(first['typical'])}\u00a0₽ по сети){more}. "
                    "Себестоимость, цены "
                    "закупки и фудкост считают эти строки как есть — исправьте накладные в учетной системе "
                    "и загрузите заново"
                ),
                effect_rub_month=None,
                effect_note="себестоимость и цены по товарам искажены",
                confidence="high",
                period_from=start,
                period_to=end,
                actions=[
                    "Проверить накладные: цена, единица измерения (грамм или килограмм), сумма",
                    "Исправить в учетной системе и загрузить закупки заново",
                ],
                evidence={"kind": "prices", "lines": lines, "products": products},
            )
        )
    return drafts


def _money(value: str) -> str:
    """1099.85 → «1 099,85»."""
    return f"{Decimal(value):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _lines(n: int) -> str:
    return (
        "строка"
        if n % 10 == 1 and n % 100 != 11
        else "строки"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
        else "строк"
    )


def _partial_counts(facts: Facts, cfg: EngineParams) -> list[Draft]:
    """The latest count of a restaurant without products it counted in each of the counts before."""
    by_day: dict[UUID, dict[date, set[UUID]]] = defaultdict(lambda: defaultdict(set))
    for c in facts.counts:
        by_day[c.restaurant][c.day].add(c.product)
    bought_since: dict[UUID, set[UUID]] = defaultdict(set)
    drafts = []
    for restaurant, days in by_day.items():
        ordered = sorted(days)
        if len(ordered) < cfg.M7_COUNT_HISTORY + 1:
            continue
        last, before = ordered[-1], ordered[-1 - cfg.M7_COUNT_HISTORY : -1]
        usual = set.intersection(*(days[d] for d in before))
        bought_since[restaurant] = {
            r.product for r in facts.receipts if r.restaurant == restaurant and before[-1] < r.day <= last
        }
        missing = sorted(
            (p for p in usual - days[last] if p in bought_since[restaurant] and p in facts.products),
            key=lambda p: facts.products[p].code,
        )
        if not missing:
            continue
        code = facts.restaurants[restaurant]
        names = [facts.products[p].name for p in missing]
        codes = [facts.products[p].code for p in missing]
        drafts.append(
            Draft(
                key=f"M7:{code}:partial:{'-'.join(codes)}",
                module="M7",
                kind="problem",
                process="inventory",
                restaurant=restaurant,
                title=f"Инвентаризация {dmy(last)} без части товаров: {len(missing)}",
                headline=(
                    f"В инвентаризации {dmy(last)} нет товаров, которые ресторан пересчитывает всегда: "
                    + ", ".join(n.lower() for n in names)
                    + ". Их закупали, но остаток не пересчитан — потери по ним до следующей полной "
                    "инвентаризации не посчитать"
                ),
                effect_rub_month=None,
                effect_note="потери по этим товарам не считаются",
                confidence="high",
                period_from=before[-1] + timedelta(days=1),
                period_to=last,
                actions=[
                    "Проверить, пересчитаны ли эти товары и не потерялись ли строки при выгрузке",
                    "Досчитать товары и загрузить инвентаризацию заново",
                ],
                evidence={
                    "kind": "partial",
                    "count_day": last.isoformat(),
                    "before": [d.isoformat() for d in before],
                    "missing": codes,
                    "product": codes[0],
                    "counted": len(days[last]),
                },
            )
        )
    return drafts


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
