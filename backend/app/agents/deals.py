"""№ 4. Negotiating with a supplier for the whole network (docs/07 «ИИ-агенты», ADR 0010; stage 11).

The restaurants of a network buy the same product from the same supplier at different prices. Over the last
eight weeks of the network's invoices (up to the latest invoice — data that is late does not move the window
to empty days), for each product a supplier sells to at least three restaurants:
- the price each restaurant paid on average (a line without a sum — an export defect — is left out);
- the network's median price: the level the supplier already gives to half of the network;
- what the restaurants above the median would have saved paying it, per month.
A supplier is worth a letter when that saving reaches `MIN_SAVING` a month. The note also gives what the
network buys from the supplier in a month and what each 1 % of discount on it is worth — the HQ's argument
for a discount on volume. The letter asks for a single price at the median and a discount on volume; the HQ
copies and sends it, «Отправлено» records that. One note per supplier and month: dismissed this month, it
comes back next month if the prices still differ.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import Product, Supplier
from app.operations.models import Receipt
from app.tenancy.models import Restaurant

WINDOW_DAYS = 56  # eight weeks of invoices
MONTH_DAYS = Decimal(30)
MIN_RESTAURANTS = 3  # a median of two is one of them: no «level of the network»
MIN_SAVING = Decimal(3000)  # ₽ a month for the whole supplier: below it a letter is not worth the HQ's time
TOP_SUPPLIERS = 3
MAX_PRODUCTS = 6  # in the list; the total counts them all
MIN_LINE = Decimal(500)  # ₽ a month: a product saving less is counted in the total, not listed


def _rub(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Line:
    restaurant_id: UUID
    qty: Decimal
    amount: Decimal

    @property
    def price(self) -> Decimal:
        return self.amount / self.qty


def _product(product: Product, lines: list[Line], per_month: Decimal) -> dict[str, str | int] | None:
    if len(lines) < MIN_RESTAURANTS:
        return None
    level = Decimal(median(sorted(x.price for x in lines)))
    saving = sum((x.amount - level * x.qty for x in lines if x.price > level), Decimal(0)) * per_month
    qty = sum((x.qty for x in lines), Decimal(0)) * per_month
    spend = sum((x.amount for x in lines), Decimal(0)) * per_month
    return {
        "product": product.name,
        "unit": product.base_unit,
        "restaurants": len(lines),
        "above": sum(1 for x in lines if x.price > level),
        "low": _rub(min(x.price for x in lines)),
        "median": _rub(level),
        "high": _rub(max(x.price for x in lines)),
        "qty_month": plain(qty.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
        "spend_month": _rub(spend),
        "saving_month": _rub(saving),
    }


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    last = session.execute(select(func.max(Receipt.day)).where(Receipt.day <= today)).scalar_one()
    if last is None:
        return []
    since = last - timedelta(days=WINDOW_DAYS - 1)
    rows = session.execute(
        select(
            Receipt.supplier_id,
            Receipt.product_id,
            Receipt.restaurant_id,
            func.sum(Receipt.qty),
            func.sum(Receipt.amount),
        )
        .where(
            Receipt.day >= since,
            Receipt.day <= last,
            Receipt.supplier_id.is_not(None),
            Receipt.qty > 0,
            Receipt.amount > 0,
        )
        .group_by(Receipt.supplier_id, Receipt.product_id, Receipt.restaurant_id)
    ).all()
    bought: dict[UUID, dict[UUID, list[Line]]] = defaultdict(lambda: defaultdict(list))
    for supplier_id, product_id, restaurant_id, qty, amount in rows:
        if supplier_id is None:
            continue
        bought[supplier_id][product_id].append(Line(restaurant_id, qty, amount))
    suppliers = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    products = {p.id: p for p in session.execute(select(Product)).scalars()}
    per_month = MONTH_DAYS / WINDOW_DAYS
    found = []
    for supplier_id, by_product in bought.items():
        lines = [
            x
            for pid, ls in by_product.items()
            if pid in products and (x := _product(products[pid], ls, per_month)) is not None
        ]
        lines.sort(key=lambda x: (-Decimal(str(x["saving_month"])), str(x["product"])))
        saving = sum((Decimal(str(x["saving_month"])) for x in lines), Decimal(0))
        listed = [x for x in lines if Decimal(str(x["saving_month"])) >= MIN_LINE]
        # Many small savings add up to a letter, but the letter needs a product to name (review, p. 1).
        if saving < MIN_SAVING or supplier_id not in suppliers or not listed:
            continue
        spend = (
            sum((ln.amount for ls in by_product.values() for ln in ls), Decimal(0)) * per_month
        )  # every product of the supplier, the ones bought by fewer restaurants too
        supplier = suppliers[supplier_id]
        found.append(
            (
                saving,
                NoteDraft(
                    agent=Agent.SUPPLIER_DEAL,
                    audience=Audience.HQ,
                    restaurant_id=None,
                    key=f"supplier_deal:{supplier.code}:{last.strftime('%Y-%m')}",
                    for_date=last,
                    facts={
                        "supplier": supplier.name,
                        "since": since.isoformat(),
                        "until": last.isoformat(),
                        "restaurants": len({ln.restaurant_id for ls in by_product.values() for ln in ls}),
                        "spend_month": _rub(spend),
                        "one_pct_month": _rub(spend / 100),
                        "saving_month": _rub(saving),
                        "products": [x for x in lines if Decimal(str(x["saving_month"])) >= MIN_LINE][
                            :MAX_PRODUCTS
                        ],
                        "products_total": sum(
                            1 for x in lines if Decimal(str(x["saving_month"])) >= MIN_LINE
                        ),
                    },
                    proposal={"action": "claim"},
                ),
            )
        )
    found.sort(key=lambda x: (-x[0], x[1].key))
    return [d for _, d in found[:TOP_SUPPLIERS]]
