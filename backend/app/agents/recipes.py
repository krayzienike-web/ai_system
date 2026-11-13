"""№ 6. Updating a recipe card the whole network overspends (docs/07 «ИИ-агенты», ADR 0010; stage 11).

The engine's M1 finds a product most restaurants use more of than the recipe cards say, by about the same
share (`M1:net:<product>`, «Техкарта, вероятно, устарела»): the card is wrong, not the kitchens. For such a
finding — open and checked — the agent proposes the new quantity for every dish and semi-product the
product goes into: the current quantity raised by the network's median overspend above the allowance, so
after the change a kitchen working as usual stays within the allowance. And what the change does to the
cost of each dish at the network's current price, and to the cost of the month's sales: money that is spent
already — the change makes the food cost true, it does not add spending.

The new quantity is a proposal: the chef changes the card in the accounting system, and the next export of
recipe cards brings it here. The HQ copies the note to the chef; «Отправлено» records that.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import MenuItem, Product, RecipeLine
from app.insights.models import Finding, FindingStatus
from app.operations.models import Receipt, Sale
from app.tenancy.models import Restaurant

OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)
WINDOW_DAYS = 56  # the price and the sales of the last eight weeks
MONTH_DAYS = Decimal(30)
QTY_PLACES = Decimal("0.001")


def _rub(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _current_lines(session: Session, product_id: UUID, today: date) -> list[RecipeLine]:
    """The lines of the product in force today: for each dish or semi-product, the latest version."""
    latest: dict[UUID, RecipeLine] = {}
    rows = session.execute(
        select(RecipeLine).where(RecipeLine.product_id == product_id, RecipeLine.valid_from <= today)
    ).scalars()
    for line in rows:
        parent = line.menu_item_id or line.semi_product_id
        if parent is None:
            continue
        if parent not in latest or line.valid_from > latest[parent].valid_from:
            latest[parent] = line
    return list(latest.values())


def _draft(session: Session, f: Finding, today: date) -> NoteDraft | None:
    ev = f.evidence or {}
    product = session.execute(select(Product).where(Product.code == ev.get("product"))).scalar_one_or_none()
    if product is None or "median_share" not in ev:
        return None
    share, allowance = Decimal(ev["median_share"]), Decimal(ev["allowance"])
    raise_by = share - allowance
    if raise_by <= 0:
        return None
    lines = _current_lines(session, product.id, today)
    if not lines:
        return None
    # The price and the sales: the last eight weeks up to the latest data (the network's, not today).
    last = session.execute(select(func.max(Sale.day)).where(Sale.day <= today)).scalar_one() or today
    since = last - timedelta(days=WINDOW_DAYS - 1)
    qty, amount = session.execute(
        select(func.sum(Receipt.qty), func.sum(Receipt.amount)).where(
            Receipt.product_id == product.id,
            Receipt.day >= since,
            Receipt.day <= last,
            Receipt.qty > 0,
            Receipt.amount > 0,
        )
    ).one()
    price = amount / qty if qty else None
    sold: dict[UUID, Decimal] = defaultdict(Decimal)
    for item_id, n in session.execute(
        select(Sale.menu_item_id, func.sum(Sale.qty))
        .where(Sale.day >= since, Sale.day <= last)
        .group_by(Sale.menu_item_id)
    ).all():
        sold[item_id] = n
    items = {m.id: m for m in session.execute(select(MenuItem)).scalars()}
    semis = {p.id: p for p in session.execute(select(Product).where(Product.is_semi.is_(True))).scalars()}
    per_month = MONTH_DAYS / WINDOW_DAYS
    dishes = []
    month_total = Decimal(0)
    for line in lines:
        new = (line.gross_qty * (1 + raise_by)).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
        if new == line.gross_qty:
            continue
        cost = (new - line.gross_qty) * price if price is not None else None
        if line.menu_item_id is not None and line.menu_item_id in items:
            name, semi = items[line.menu_item_id].name, False
            month = cost * sold[line.menu_item_id] * per_month if cost is not None else None
        elif line.semi_product_id is not None and line.semi_product_id in semis:
            name, semi, month = semis[line.semi_product_id].name, True, None  # its dishes carry it
        else:
            continue
        if month is not None:
            month_total += month
        dishes.append(
            {
                "name": name,
                "semi": semi,
                "old": plain(line.gross_qty),
                "new": plain(new),
                "cost": _rub(cost) if cost is not None else None,
                "month": _rub(month) if month is not None else None,
            }
        )
    if not dishes:
        return None
    dishes.sort(key=lambda d: (d["semi"], d["name"]))
    restaurants = ev.get("restaurants") or {}
    return NoteDraft(
        agent=Agent.RECIPE_UPDATE,
        audience=Audience.HQ,
        restaurant_id=None,
        key=f"recipe_update:{f.key}",
        for_date=f.period_to or today,
        facts={
            "finding": f.title,
            "product": product.name,
            "unit": product.base_unit,
            "median_pct": plain((share * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "allowance_pct": plain((allowance * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "raise_pct": plain((raise_by * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "restaurants_over": sum(1 for s in restaurants.values() if Decimal(s) > allowance),
            "restaurants": len(restaurants),
            "since": f.period_from.isoformat() if f.period_from else None,
            "until": f.period_to.isoformat() if f.period_to else None,
            "price": _rub(price) if price is not None else None,
            "dishes": dishes,
            "month_cost": _rub(month_total),
        },
        proposal={"action": "claim"},
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    found = session.execute(
        select(Finding)
        .where(
            Finding.module == "M1",
            Finding.restaurant_id.is_(None),
            Finding.status.in_(OPEN),
            Finding.key.like("M1:net:%"),
        )
        .order_by(Finding.key)
    ).scalars()
    return [d for f in found if f.checked and (d := _draft(session, f, today)) is not None]
