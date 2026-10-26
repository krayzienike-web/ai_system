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
