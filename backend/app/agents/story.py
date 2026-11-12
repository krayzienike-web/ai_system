"""№ 2. A large shortage, told as a story (docs/07 «ИИ-агенты», ADR 0010; stage 10).

For an open M1 finding of a restaurant and a product («Перерасход по техкарте») of at least `MIN_RUB_MONTH`,
the analyst gets the product's timeline between the restaurant's counts — the finding's own periods: used by
the counts, by the recipes, written off — with what was bought from whom and moved in and out over each.
Versions come from rules over that timeline, two or three, with what to check on the spot:
- a new supplier in the window: the weight or the pack may differ;
- nothing written off while the use runs above the recipes: spoiled or wasted goes unrecorded;
- moved out to other restaurants: is it in their books;
- the overuse grows from count to count: something changed;
- above the recipes every time: the portions, or the recipe is out of date.
The analyst draws the conclusion: the note proposes nothing.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import Product, Supplier
from app.insights.models import Finding, FindingStatus, ReviewStatus
from app.operations.models import Receipt, Transfer
from app.tenancy.models import Restaurant

MIN_RUB_MONTH = Decimal(10_000)
NO_SUPPLIER = (
    "без поставщика"  # receipts with no supplier: not a supplier of their own (backend review, p. 8)
)
MAX_VERSIONS = 3
GROWING = Decimal("1.5")  # the last period's overuse this many times the first one's
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


def _q(value: Decimal) -> str:
    return plain(value.quantize(Decimal("0.1")))


def _period(
    session: Session, restaurant: Restaurant, product: Product, p: dict[str, Any], suppliers: dict[Any, str]
) -> dict[str, Any]:
    start, end = date.fromisoformat(p["from"]), date.fromisoformat(p["to"])
    bought: dict[str, Decimal] = defaultdict(Decimal)
    for supplier_id, qty in session.execute(
        select(Receipt.supplier_id, func.sum(Receipt.qty))
        .where(
            Receipt.restaurant_id == restaurant.id,
            Receipt.product_id == product.id,
            Receipt.day >= start,
            Receipt.day <= end,
        )
        .group_by(Receipt.supplier_id)
    ):
        bought[suppliers.get(supplier_id, NO_SUPPLIER)] += qty

    def moved(column: Any) -> Decimal:
        return Decimal(
            session.execute(
                select(func.coalesce(func.sum(Transfer.qty), 0)).where(
                    column == restaurant.id,
                    Transfer.product_id == product.id,
                    Transfer.day >= start,
                    Transfer.day <= end,
                )
            ).scalar_one()
        )

    return {
        "from": p["from"],
        "to": p["to"],
        "actual": _q(Decimal(p["actual"])),
        "theory": _q(Decimal(p["theory"])),
        "share": plain((Decimal(p["share"]) * 100).quantize(Decimal("0.1"))),
        # Three decimals: 0,03 kg written off is not «nothing written off» (backend review, p. 8)
        "written_off": plain(Decimal(p["write_off"]).quantize(Decimal("0.001"))),
        "bought": {name: _q(qty) for name, qty in sorted(bought.items())},
        "moved_in": _q(moved(Transfer.to_restaurant_id)),
        "moved_out": _q(moved(Transfer.restaurant_id)),
    }


def versions(periods: list[dict[str, Any]], benchmark: Decimal) -> list[str]:
    """The rules, most specific first; at least one — the overuse itself."""
    out = []
    names = [set(p["bought"]) - {NO_SUPPLIER} for p in periods]
    if len(set().union(*names)) > 1:
        out.append("supplier")
    if all(Decimal(p["written_off"]) == 0 for p in periods):
        out.append("no_write_offs")
    if any(Decimal(p["moved_out"]) > 0 for p in periods):
        out.append("moved_out")
    shares = [Decimal(p["share"]) for p in periods]
    if len(shares) > 1 and shares[0] > 0 and shares[-1] >= shares[0] * GROWING:
        out.append("growing")
    if all(s > benchmark * 100 for s in shares) and len(out) < MAX_VERSIONS:
        out.append("portions")
    return (out or ["portions"])[:MAX_VERSIONS]


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    places = {r.id: r for r in restaurants}
    suppliers = {s.id: s.name for s in session.execute(select(Supplier)).scalars()}
    out = []
    for f in session.execute(
        select(Finding)
        .where(
            Finding.module == "M1",
            Finding.status.in_(OPEN),
            Finding.restaurant_id.is_not(None),
            Finding.effect_rub_month >= MIN_RUB_MONTH,
            # a rejected finding is wrong: nothing builds on it (test engineer, stage 10, TC-AG-36)
            Finding.review_status.is_distinct_from(ReviewStatus.REJECTED),
        )
        .order_by(Finding.key)
    ).scalars():
        ev = f.evidence or {}
        parts = (f.key or "").split(":")
        restaurant = places.get(f.restaurant_id) if f.restaurant_id else None
        product = session.execute(
            select(Product).where(Product.code == ev.get("product"))
        ).scalar_one_or_none()
        if len(parts) != 3 or restaurant is None or product is None or not ev.get("periods"):
            continue  # «:under» (below the recipes) is not a shortage
        periods = [_period(session, restaurant, product, p, suppliers) for p in ev["periods"]]
        benchmark = Decimal(ev.get("benchmark") or "0")
        out.append(
            NoteDraft(
                agent=Agent.SHORTAGE_STORY,
                audience=Audience.HQ,
                restaurant_id=restaurant.id,
                key=f"shortage_story:{f.key}",
                for_date=f.period_to or today,
                facts={
                    "finding": f.title,
                    "restaurant": restaurant.name,
                    "product": product.name,
                    "unit": product.base_unit,
                    "effect": str(f.effect_rub_month.quantize(Decimal(1))) if f.effect_rub_month else None,
                    "network_share": plain((benchmark * 100).quantize(Decimal("0.1"))),
                    "periods": periods,
                    "versions": versions(periods, benchmark),
                },
            )
        )
    return out
