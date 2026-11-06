"""M3. Purchase prices: where a restaurant pays more than the rest of the network for the same product.

Over the last 8 weeks of purchases, each restaurant's average price of a product (weighted by quantity)
is compared with the typical price of the other restaurants (their median). The explanation names the
supplier: a more expensive supplier than the others use, or the same supplier charging this restaurant
more. See docs/12-analytics-engine.md (M3).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts, ReceiptRow
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.stats import med, robust_z

ACTIONS_SUPPLIER = [
    "Заказывать у основного поставщика заранее, по графику поставок",
    "Разобрать, почему понадобились срочные закупки: остатки, прогноз, график",
]
ACTIONS_SAME_SUPPLIER = [
    "Запросить у поставщика цену, как у других ресторанов сети",
    "Перевести закупку на единый договор сети",
]


@dataclass
class PriceRow:
    restaurant: UUID
    product: UUID
    qty: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    receipts: list[ReceiptRow] = field(default_factory=list)

    @property
    def price(self) -> Decimal:
        return self.amount / self.qty

    def main_supplier(self) -> UUID | None:
        by: dict[UUID | None, Decimal] = defaultdict(Decimal)
        for r in self.receipts:
            by[r.supplier] += r.amount
        return max(by, key=lambda s: by[s])


def window(facts: Facts, cfg: EngineParams = DEFAULT) -> tuple[date, date] | None:
    if not facts.receipts:
        return None
    end = max(r.day for r in facts.receipts)
    return end - timedelta(days=cfg.M3_WINDOW_DAYS - 1), end


def rows(facts: Facts, start: date, end: date) -> dict[UUID, dict[UUID, PriceRow]]:
    """product -> restaurant -> purchases in the window."""
    out: dict[UUID, dict[UUID, PriceRow]] = defaultdict(dict)
    for r in facts.receipts:
        if start <= r.day <= end and r.qty > 0:
            row = out[r.product].setdefault(r.restaurant, PriceRow(r.restaurant, r.product))
            row.qty += r.qty
            row.amount += r.amount
            row.receipts.append(r)
    return out


def since(receipts: list[ReceiptRow], threshold: Decimal) -> date:
    """The first day of the latest unbroken run of purchases above `threshold` (₽ per unit)."""
    ordered = sorted(receipts, key=lambda r: r.day)
    first = ordered[-1].day
    for r in reversed(ordered):
        if r.amount / r.qty <= threshold:
            break
        first = r.day
    return first


def detect(facts: Facts, cfg: EngineParams = DEFAULT) -> list[Draft]:
    span = window(facts, cfg)
    if span is None:
        return []
    start, end = span
    days = (end - start).days + 1
    history: dict[tuple[UUID, UUID], list[ReceiptRow]] = defaultdict(list)
    for r in facts.receipts:
        if r.day <= end and r.qty > 0:
            history[(r.restaurant, r.product)].append(r)
    drafts: list[Draft] = []
    for product, by_restaurant in rows(facts, start, end).items():
        valid = {
            r: row
            for r, row in by_restaurant.items()
            if len(row.receipts) >= cfg.M3_MIN_RECEIPTS and row.qty > 0 and row.amount > 0
        }
        if len(valid) < 3:
            continue
        info = facts.products[product]
        prices = [row.price for row in valid.values()]
        network_median = med(prices)
        for restaurant, row in valid.items():
            others = [o for r, o in valid.items() if r != restaurant]
            bench = med([o.price for o in others])
            if bench <= 0:
                continue
            share = row.price / bench - 1
            if share <= cfg.M3_OVERPAY:
                continue
            z = None
            if len(valid) >= cfg.NETWORK_Z_MIN_RESTAURANTS:
                z = robust_z(row.price / network_median, [p / network_median for p in prices], cfg.M3_Z_FLOOR)
                if z <= cfg.M3_Z:
                    continue
            effect = per_month((row.price - bench) * row.qty, start, end)
            if effect < cfg.M3_MATERIALITY_RUB_MONTH:
                continue
            supplier = row.main_supplier()
            others_suppliers = {o.main_supplier() for o in others}
            own_name = facts.suppliers.get(supplier, "поставщик") if supplier else "поставщик"
            different = supplier not in others_suppliers
            # Since when: over the whole purchase history, not only the window.
            start_day = since(history[(restaurant, product)], bench * (1 + cfg.M3_OVERPAY / 2))
            unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)
            price_text = f"{rub(row.price)}/{unit}"
            if different:
                usual = {facts.suppliers.get(s, "") for s in others_suppliers if s}
                title = f"Закупка у дорогого поставщика: {info.name}"
                headline = (
                    f"С {dmy(start_day)} {info.name.lower()} покупают у «{own_name}» по {price_text} — на "
                    f"{pct(share, 0)} дороже, чем в среднем по сети ({rub(bench)}/{unit}), где берут у "
                    + ", ".join(f"«{u}»" for u in sorted(usual) if u)
                    + f". Переплата ≈ {rub(effect)} в месяц"
                )
                actions = list(ACTIONS_SUPPLIER)
            else:
                title = f"Поставщик продает дороже, чем другим: {info.name}"
                headline = (
                    f"С {dmy(start_day)} «{own_name}» продает {info.name.lower()} этому ресторану "
                    f"по {price_text} — на "
                    f"{pct(share, 0)} дороже, чем другим ресторанам сети ({rub(bench)}/{unit}). "
                    f"Переплата ≈ {rub(effect)} в месяц"
                )
                actions = list(ACTIONS_SAME_SUPPLIER)
            drafts.append(
                Draft(
                    key=f"M3:{facts.restaurants[restaurant]}:{info.code}",
                    module="M3",
                    kind="problem",
                    process="purchasing",
                    restaurant=restaurant,
                    title=title,
                    headline=headline,
                    effect_rub_month=effect,
                    effect_note=None,
                    confidence="high" if len(row.receipts) >= 4 else "medium",
                    period_from=start,
                    period_to=end,
                    actions=actions,
                    evidence={
                        "product": info.code,
                        "price": str(row.price.quantize(Decimal("0.01"))),
                        "benchmark": str(bench.quantize(Decimal("0.01"))),
                        "share": str(share.quantize(Decimal("0.0001"))),
                        "qty": str(row.qty.quantize(Decimal("0.001"))),
                        "days": days,
                        "since": start_day.isoformat(),
                        "supplier": own_name,
                        "other_supplier": different,
                        "z": None if z is None else str(z.quantize(Decimal("0.01"))),
                        "network": {
                            facts.restaurants[r]: str(o.price.quantize(Decimal("0.01")))
                            for r, o in valid.items()
                        },
                    },
                )
            )
    return drafts


ACTIONS_CONTRACT = [
    "Предъявить поставщику расхождение с договором и вернуть переплату",
    "Включить сверку цен накладных с договором в приемку",
]
ACTIONS_NET_GROWTH = [
    "Проверить, согласован ли рост цены с поставщиком и закреплен ли он в договоре",
    "Запросить предложения других поставщиков",
    "Пересмотреть цены блюд, где этот товар — основной ингредиент",
]


def _network_price(receipts: list[ReceiptRow]) -> Decimal | None:
    qty = sum((r.qty for r in receipts), Decimal(0))
    return None if qty <= 0 else sum((r.amount for r in receipts), Decimal(0)) / qty


def detect_contracts(facts: Facts, cfg: EngineParams = DEFAULT) -> list[Draft]:
    """Invoices above the price agreed with the supplier (when contract prices are loaded)."""
    span = window(facts, cfg)
    if span is None or not facts.contracts:
        return []
    start, end = span
    by_pair: dict[tuple[UUID, UUID], list[tuple[ReceiptRow, Decimal]]] = defaultdict(list)
    contracts: dict[tuple[UUID, UUID], list] = defaultdict(list)  # type: ignore[type-arg]
    for c in facts.contracts:
        contracts[(c.supplier, c.product)].append(c)
    for r in facts.receipts:
        if not (start <= r.day <= end) or r.supplier is None or r.qty <= 0:
            continue
        valid = [c for c in contracts.get((r.supplier, r.product), []) if c.covers(r.day)]
        if valid:
            price = max(valid, key=lambda c: c.valid_from).price
            by_pair[(r.supplier, r.product)].append((r, price))
    drafts = []
    for (supplier, product), rows in by_pair.items():
        over = [(r, p) for r, p in rows if r.amount / r.qty > p * (1 + cfg.M3_CONTRACT_TOLERANCE)]
        if not over:
            continue
        overpay = sum((r.amount - p * r.qty for r, p in over), Decimal(0))
        effect = per_month(overpay, start, end)
        if effect < cfg.M3_MATERIALITY_RUB_MONTH:
            continue
        info = facts.products[product]
        name = facts.suppliers.get(supplier, "поставщик")
        contract_price = max(p for _, p in over)
        paid = _network_price([r for r, _ in over]) or Decimal(0)
        share = paid / contract_price - 1
        by_restaurant: dict[str, Decimal] = defaultdict(Decimal)
        for r, p in over:
            by_restaurant[facts.restaurants[r.restaurant]] += r.amount - p * r.qty
        unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)
        drafts.append(
            Draft(
                key=f"M3:net:{info.code}:contract",
                module="M3",
                kind="problem",
                process="purchasing",
                restaurant=None,
                title=f"Цена выше договорной: {info.name}",
                headline=(
                    f"«{name}» выставляет {info.name.lower()} в среднем по {rub(paid)}/{unit} при договорной "
                    f"{rub(contract_price)}/{unit} (+{pct(share, 0)}) — в {len(over)} накладных "
                    f"{len(by_restaurant)} ресторанов. Переплата ≈ {rub(effect)} в месяц"
                ),
                effect_rub_month=effect,
                effect_note=None,
                confidence="high",
                period_from=start,
                period_to=end,
                actions=list(ACTIONS_CONTRACT),
                evidence={
                    "kind": "contract",
                    "product": info.code,
                    "supplier": name,
                    "contract_price": str(contract_price.quantize(Decimal("0.01"))),
                    "paid": str(paid.quantize(Decimal("0.01"))),
                    "overpay": str(overpay.quantize(Decimal("0.01"))),
                    "receipts": len(over),
                    "restaurants": {
                        k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(by_restaurant.items())
                    },
                },
            )
        )
    return drafts


def detect_network_growth(facts: Facts, cfg: EngineParams = DEFAULT) -> list[Draft]:
    """The whole network pays noticeably more than a quarter ago (no contract price to compare with)."""
    if not facts.receipts:
        return []
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M3_NET_WINDOW_DAYS - 1)
    before_end = end - timedelta(days=cfg.M3_NET_COMPARE_DAYS)
    before_start = before_end - timedelta(days=cfg.M3_NET_WINDOW_DAYS - 1)
    with_contract = {c.product for c in facts.contracts}
    now: dict[UUID, list[ReceiptRow]] = defaultdict(list)
    before: dict[UUID, list[ReceiptRow]] = defaultdict(list)
    history: dict[UUID, list[ReceiptRow]] = defaultdict(list)
    for r in facts.receipts:
        if r.qty <= 0:
            continue
        if start <= r.day <= end:
            now[r.product].append(r)
        elif before_start <= r.day <= before_end:
            before[r.product].append(r)
        if r.day <= end:
            history[r.product].append(r)
    drafts = []
    for product, rows in now.items():
        if product in with_contract or product not in before:
            continue
        p_now, p_before = _network_price(rows), _network_price(before[product])
        if not p_now or not p_before:
            continue
        growth = p_now / p_before - 1
        if growth <= cfg.M3_NET_GROWTH:
            continue
        qty = sum((r.qty for r in rows), Decimal(0))
        effect = per_month((p_now - p_before) * qty, start, end)
        if effect < cfg.M3_MATERIALITY_RUB_MONTH:
            continue
        info = facts.products[product]
        restaurants = {r.restaurant for r in rows}
        by_supplier: dict[UUID | None, Decimal] = defaultdict(Decimal)
        for r in rows:
            by_supplier[r.supplier] += r.amount
        main = max(by_supplier, key=lambda s: by_supplier[s])
        name = facts.suppliers.get(main, "поставщик") if main else "поставщик"
        start_day = since(history[product], p_before * (1 + cfg.M3_NET_GROWTH / 2))
        unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)
        drafts.append(
            Draft(
                key=f"M3:net:{info.code}:growth",
                module="M3",
                kind="problem",
                process="purchasing",
                restaurant=None,
                title=f"Цена выросла по всей сети: {info.name}",
                headline=(
                    f"С {dmy(start_day)} {info.name.lower()} обходится сети в {rub(p_now)}/{unit} "
                    f"вместо {rub(p_before)}/{unit} кварталом раньше (+{pct(growth, 0)}), основной "
                    f"поставщик — «{name}», закупают {len(restaurants)} ресторанов. "
                    f"Это ≈ {rub(effect)} в месяц сверх прежней цены. "
                    "Проверьте, согласован ли рост с поставщиком"
                ),
                effect_rub_month=effect,
                effect_note=None,
                confidence="high" if len(restaurants) >= 3 else "medium",
                period_from=start,
                period_to=end,
                actions=list(ACTIONS_NET_GROWTH),
                evidence={
                    "kind": "growth",
                    "product": info.code,
                    "supplier": name,
                    "price": str(p_now.quantize(Decimal("0.01"))),
                    "price_before": str(p_before.quantize(Decimal("0.01"))),
                    "before": [before_start.isoformat(), before_end.isoformat()],
                    "growth": str(growth.quantize(Decimal("0.0001"))),
                    "qty": str(qty.quantize(Decimal("0.001"))),
                    "since": start_day.isoformat(),
                    "restaurants": len(restaurants),
                },
            )
        )
    return drafts


ACTIONS_JUMP = [
    "Запросить у поставщика, почему цена выросла: прайс, скидка, условия договора",
    "Сравнить с ценами этого товара в других ресторанах сети и у других поставщиков",
]


def _avg(rows: list[ReceiptRow]) -> Decimal | None:
    qty = sum((r.qty for r in rows), Decimal(0))
    amount = sum((r.amount for r in rows), Decimal(0))
    return amount / qty if qty > 0 and amount > 0 else None


def jump_windows(facts: Facts, cfg: EngineParams = DEFAULT) -> tuple[date, date, date, date] | None:
    """The last weeks and the restaurant's own weeks before them: (start, end, base_start, base_end)."""
    if not facts.receipts:
        return None
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M3_JUMP_WINDOW_DAYS - 1)
    base_end = start - timedelta(days=1)
    return start, end, base_end - timedelta(days=cfg.M3_JUMP_BASE_DAYS - 1), base_end


def detect_jumps(
    facts: Facts, cfg: EngineParams = DEFAULT, covered: list[Draft] | None = None
) -> list[Draft]:
    """A restaurant pays noticeably more than it used to pay itself, beyond how the others' price moved.

    Not shown when the restaurant's overpayment against the network is already a finding (`covered`) or the
    product has contract prices (the contract check says it better)."""
    span = jump_windows(facts, cfg)
    if span is None:
        return []
    start, end, base_start, base_end = span
    taken = {(d.restaurant, d.evidence.get("product")) for d in covered or [] if d.restaurant is not None}
    with_contract = {c.product for c in facts.contracts}
    now: dict[tuple[UUID, UUID], list[ReceiptRow]] = defaultdict(list)
    base: dict[tuple[UUID, UUID], list[ReceiptRow]] = defaultdict(list)
    history: dict[tuple[UUID, UUID], list[ReceiptRow]] = defaultdict(list)
    for r in facts.receipts:
        if r.qty <= 0 or r.day > end:
            continue
        history[(r.restaurant, r.product)].append(r)
        if start <= r.day:
            now[(r.restaurant, r.product)].append(r)
        elif base_start <= r.day <= base_end:
            base[(r.restaurant, r.product)].append(r)
    growth: dict[tuple[UUID, UUID], tuple[Decimal, Decimal, Decimal]] = {}  # (growth, price, base price)
    for pair, rows in now.items():
        before = base.get(pair, [])
        if len(rows) < cfg.M3_MIN_RECEIPTS or len(before) < cfg.M3_MIN_RECEIPTS:
            continue
        p_now, p_base = _avg(rows), _avg(before)
        if p_now and p_base:
            growth[pair] = (p_now / p_base - 1, p_now, p_base)
    by_product: dict[UUID, list[tuple[UUID, Decimal]]] = defaultdict(list)  # once, not per pair
    for (place, item), v in growth.items():
        by_product[item].append((place, v[0]))
    drafts = []
    for (restaurant, product), (g, p_now, p_base) in growth.items():
        if product in with_contract or product not in facts.products:
            continue
        info = facts.products[product]
        if (restaurant, info.code) in taken:
            continue
        others = [x for place, x in by_product[product] if place != restaurant]
        moved = med(others) if others else Decimal(0)  # how the price moved for the rest of the network
        excess = g - moved
        if excess <= cfg.M3_JUMP:
            continue
        rows = now[(restaurant, product)]
        qty = sum((r.qty for r in rows), Decimal(0))
        expected = p_base * (1 + moved)
        effect = per_month((p_now - expected) * qty, start, end)
        if effect < cfg.M3_MATERIALITY_RUB_MONTH:
            continue
        by_supplier: dict[UUID | None, Decimal] = defaultdict(Decimal)
        for r in rows:
            by_supplier[r.supplier] += r.amount
        main = max(by_supplier, key=lambda s: by_supplier[s])
        name = facts.suppliers.get(main, "поставщик") if main else "поставщик"
        start_day = since(history[(restaurant, product)], p_base * (1 + cfg.M3_JUMP / 2))
        unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)
        code = facts.restaurants[restaurant]
        if not others:
            network_text = "другие рестораны этот товар не закупают"
        elif abs(moved) < Decimal("0.005"):
            network_text = "у остальных ресторанов цена не изменилась"
        else:
            way = "выросла" if moved > 0 else "снизилась"
            network_text = f"у остальных ресторанов цена {way} на {pct(abs(moved), 0)}"
        drafts.append(
            Draft(
                key=f"M3:{code}:{info.code}:jump",
                module="M3",
                kind="problem",
                process="purchasing",
                restaurant=restaurant,
                title=f"Цена выше, чем ресторан платил раньше: {info.name}",
                headline=(
                    f"С {dmy(start_day)} {info.name.lower()} у «{name}» обходится ресторану в "
                    f"{rub(p_now)}/{unit} вместо прежних {rub(p_base)}/{unit} (+{pct(g, 0)}), а "
                    f"{network_text}. Сверх прежней цены ≈ {rub(effect)} в месяц"
                ),
                effect_rub_month=effect,
                effect_note=None,
                confidence="high" if len(rows) >= 4 else "medium",
                period_from=start,
                period_to=end,
                actions=list(ACTIONS_JUMP),
                evidence={
                    "kind": "jump",
                    "product": info.code,
                    "supplier": name,
                    "price": str(p_now.quantize(Decimal("0.01"))),
                    "price_before": str(p_base.quantize(Decimal("0.01"))),
                    "before": [base_start.isoformat(), base_end.isoformat()],
                    "growth": str(g.quantize(Decimal("0.0001"))),
                    "network_growth": str(moved.quantize(Decimal("0.0001"))),
                    "qty": str(qty.quantize(Decimal("0.001"))),
                    "receipts": len(rows),
                    "since": start_day.isoformat(),
                    "restaurants": len(others),
                },
            )
        )
    return drafts
