"""№ 5. A transfer instead of a stock-out (docs/07 «ИИ-агенты», ADR 0010; stage 10).

An open M6 finding «Закончится до поставки» in restaurant A: the days from when the product runs out (not
before today) to the next delivery need, by the finding's weekday need, so much of it. Another restaurant B
can give it when its latest «Остатки на дату» (no older than `SNAPSHOT_AGE` days before A's data) hold more
than `KEEP_DAYS` of its own use — its use is what it bought over `USE_DAYS` (purchases follow use) — and B has
no stock-out of the same product itself. The one with the most to spare is proposed. The note is the HQ's:
it compares restaurants. «Поставить задачи» gives B a task to hand it over and A a task to take it in, due
on the day the product runs out; nothing moves without that.
"""

from datetime import date, timedelta
from decimal import ROUND_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import Product
from app.insights.models import Finding, FindingStatus
from app.operations.models import Receipt, StockBalance
from app.tenancy.models import Restaurant

KEEP_DAYS = 3  # the giving restaurant keeps this many days of its own use
USE_DAYS = 28  # its use: what it bought over these days
SNAPSHOT_AGE = 3  # its «Остатки на дату» no older than this before the short restaurant's data
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)
STEP = {"kg": Decimal("0.1"), "l": Decimal("0.1"), "pcs": Decimal(1)}


def _need(ev: dict[str, Any], start: date, delivery: date, unit: str) -> Decimal:
    """What the days without the product need, rounded up to a step one can weigh or count."""
    weekday = [Decimal(x) for x in ev["need_by_weekday"]]
    need = sum(
        (weekday[(start + timedelta(days=i)).weekday()] for i in range((delivery - start).days)), Decimal(0)
    )
    step = STEP.get(unit, Decimal("0.1"))
    return (need / step).to_integral_value(rounding=ROUND_UP) * step


def _spare(
    session: Session, product: Product, restaurant: Restaurant, since: date, until: date
) -> dict[str, Any] | None:
    snapshot = session.execute(
        select(StockBalance.day, StockBalance.qty)
        .where(
            StockBalance.restaurant_id == restaurant.id,
            StockBalance.product_id == product.id,
            StockBalance.day >= since,
            StockBalance.day <= until,
        )
        .order_by(StockBalance.day.desc())
        .limit(1)
    ).first()
    if snapshot is None or snapshot.qty <= 0:
        return None
    bought = session.execute(
        select(func.coalesce(func.sum(Receipt.qty), 0)).where(
            Receipt.restaurant_id == restaurant.id,
            Receipt.product_id == product.id,
            Receipt.day > until - timedelta(days=USE_DAYS),
            Receipt.day <= until,
        )
    ).scalar_one()
    daily = Decimal(bought) / USE_DAYS
    spare = snapshot.qty - daily * KEEP_DAYS
    return {"day": snapshot.day, "stock": snapshot.qty, "daily": daily, "spare": spare}


def _short_codes(found: list[Finding]) -> set[tuple[UUID | None, str]]:
    return {(f.restaurant_id, (f.evidence or {}).get("product", "")) for f in found}


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    found = [
        f
        for f in session.execute(
            select(Finding)
            .where(
                Finding.module == "M6",
                Finding.status.in_(OPEN),
                Finding.key.like("%:shortage"),
                Finding.restaurant_id.is_not(None),
            )
            .order_by(Finding.key)
        ).scalars()
    ]
    short = _short_codes(found)
    places = {r.id: r for r in restaurants}
    out = []
    for f in found:
        ev = f.evidence or {}
        product = session.execute(
            select(Product).where(Product.code == ev.get("product"))
        ).scalar_one_or_none()
        short_place = places.get(f.restaurant_id) if f.restaurant_id else None
        if product is None or short_place is None:
            continue
        start = max(date.fromisoformat(ev["zero_day"]), today)
        delivery = date.fromisoformat(ev["next_delivery"])
        if start >= delivery:  # the delivery comes first: nothing to bridge
            continue
        need = _need(ev, start, delivery, product.base_unit)
        until = date.fromisoformat(ev["data_until"])
        best: tuple[Decimal, Restaurant, dict[str, Any]] | None = None
        for r in restaurants:
            if r.id == short_place.id or (r.id, product.code) in short:
                continue
            s = _spare(session, product, r, until - timedelta(days=SNAPSHOT_AGE), until)
            if s is not None and s["spare"] >= need and (best is None or s["spare"] > best[0]):
                best = (s["spare"], r, s)
        if best is None:
            continue
        _, giver, s = best
        out.append(
            NoteDraft(
                agent=Agent.TRANSFER,
                audience=Audience.HQ,
                restaurant_id=short_place.id,
                key=f"transfer:{f.key}",
                for_date=start,
                facts={
                    "product": product.name,
                    "unit": product.base_unit,
                    "qty": plain(need),
                    "to": short_place.name,
                    "from": giver.name,
                    "by": start.isoformat(),
                    "zero_day": ev["zero_day"],
                    "next_delivery": ev["next_delivery"],
                    "from_stock": plain(s["stock"].quantize(Decimal("0.001"))),
                    "from_stock_day": s["day"].isoformat(),
                    "from_daily": plain(s["daily"].quantize(Decimal("0.1"), rounding=ROUND_UP)),
                    "keep_days": KEEP_DAYS,
                },
                proposal={
                    "action": "transfer",
                    "due_on": start.isoformat(),
                    "from_id": str(giver.id),
                    "to_id": str(short_place.id),
                    "title": f"Перемещение: {product.name.lower()}",
                },
            )
        )
    return out
