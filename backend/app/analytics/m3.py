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

from app.analytics import params
from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts, ReceiptRow
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


def window(facts: Facts) -> tuple[date, date] | None:
    if not facts.receipts:
        return None
    end = max(r.day for r in facts.receipts)
    return end - timedelta(days=params.M3_WINDOW_DAYS - 1), end


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


def detect(facts: Facts) -> list[Draft]:
    span = window(facts)
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
        valid = {r: row for r, row in by_restaurant.items() if len(row.receipts) >= params.M3_MIN_RECEIPTS}
        if len(valid) < 3:
            continue
        info = facts.products[product]
        prices = [row.price for row in valid.values()]
        for restaurant, row in valid.items():
            others = [o for r, o in valid.items() if r != restaurant]
            bench = med([o.price for o in others])
            share = row.price / bench - 1
            if share <= params.M3_OVERPAY:
                continue
            z = None
            if len(valid) >= params.NETWORK_Z_MIN_RESTAURANTS:
                z = robust_z(row.price / med(prices), [p / med(prices) for p in prices], params.M3_Z_FLOOR)
                if z <= params.M3_Z:
                    continue
            effect = per_month((row.price - bench) * row.qty, start, end)
            if effect < params.M3_MATERIALITY_RUB_MONTH:
                continue
            supplier = row.main_supplier()
            others_suppliers = {o.main_supplier() for o in others}
            own_name = facts.suppliers.get(supplier, "поставщик") if supplier else "поставщик"
            different = supplier not in others_suppliers
            # Since when: over the whole purchase history, not only the window.
            start_day = since(history[(restaurant, product)], bench * (1 + params.M3_OVERPAY / 2))
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


def detect_contracts(facts: Facts) -> list[Draft]:
    """Invoices above the price agreed with the supplier (when contract prices are loaded)."""
    span = window(facts)
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
        over = [(r, p) for r, p in rows if r.amount / r.qty > p * (1 + params.M3_CONTRACT_TOLERANCE)]
        if not over:
            continue
        overpay = sum((r.amount - p * r.qty for r, p in over), Decimal(0))
        effect = per_month(overpay, start, end)
        if effect < params.M3_MATERIALITY_RUB_MONTH:
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


def detect_network_growth(facts: Facts) -> list[Draft]:
    """The whole network pays noticeably more than a quarter ago (no contract price to compare with)."""
    if not facts.receipts:
        return []
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=params.M3_NET_WINDOW_DAYS - 1)
    before_end = end - timedelta(days=params.M3_NET_COMPARE_DAYS)
    before_start = before_end - timedelta(days=params.M3_NET_WINDOW_DAYS - 1)
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
        if growth <= params.M3_NET_GROWTH:
            continue
        qty = sum((r.qty for r in rows), Decimal(0))
        effect = per_month((p_now - p_before) * qty, start, end)
        if effect < params.M3_MATERIALITY_RUB_MONTH:
            continue
        info = facts.products[product]
        restaurants = {r.restaurant for r in rows}
        by_supplier: dict[UUID | None, Decimal] = defaultdict(Decimal)
        for r in rows:
            by_supplier[r.supplier] += r.amount
        main = max(by_supplier, key=lambda s: by_supplier[s])
        name = facts.suppliers.get(main, "поставщик") if main else "поставщик"
        start_day = since(history[product], p_before * (1 + params.M3_NET_GROWTH / 2))
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
