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

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import MenuItem, Product, RecipeLine
from app.catalog.recipes import Line, explode, lines_on
from app.insights.models import Finding, FindingStatus
from app.operations.models import Receipt, Sale
from app.tenancy.models import Restaurant

OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)
WINDOW_DAYS = 56  # the price and the sales of the last eight weeks
MONTH_DAYS = Decimal(30)
QTY_PLACES = Decimal("0.001")


def _rub(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Network:
    """What every recipe note of one run reads: loaded once (backend review of stage 11, p. 9)."""

    recipes: dict[UUID, list[Line]]  # the version of each dish and semi-product in force today
    versions: dict[UUID, date]  # since when that version is in force
    items: dict[UUID, MenuItem]
    semis: dict[UUID, Product]
    sold: dict[UUID, Decimal]  # portions of each dish over the window
    since: date
    last: date


def _network(session: Session, today: date) -> Network:
    rows = session.execute(select(RecipeLine).where(RecipeLine.valid_from <= today)).scalars()
    lines = [
        Line(parent, r.product_id, r.gross_qty, r.valid_from)
        for r in rows
        if (parent := r.menu_item_id or r.semi_product_id) is not None
    ]
    # A version is the whole card of a dish with one start day: a product left out of the newer card is not
    # in the dish any more (backend review of stage 11, p. 2).
    recipes = lines_on(lines, today)
    last = session.execute(select(func.max(Sale.day)).where(Sale.day <= today)).scalar_one() or today
    since = last - timedelta(days=WINDOW_DAYS - 1)
    sold = dict(
        session.execute(
            select(Sale.menu_item_id, func.sum(Sale.qty))
            .where(Sale.day >= since, Sale.day <= last)
            .group_by(Sale.menu_item_id)
        ).all()
    )
    return Network(
        recipes=recipes,
        versions={parent: ls[0].valid_from for parent, ls in recipes.items()},
        items={m.id: m for m in session.execute(select(MenuItem)).scalars()},
        semis={p.id: p for p in session.execute(select(Product).where(Product.is_semi.is_(True))).scalars()},
        sold=sold,
        since=since,
        last=last,
    )


def _draft(session: Session, net: Network, f: Finding) -> NoteDraft | None:
    ev = f.evidence or {}
    product = session.execute(select(Product).where(Product.code == ev.get("product"))).scalar_one_or_none()
    if product is None or "median_share" not in ev:
        return None
    share, allowance = Decimal(ev["median_share"]), Decimal(ev["allowance"])
    raise_by = share - allowance
    if raise_by <= 0:
        return None
    qty, amount = session.execute(
        select(func.sum(Receipt.qty), func.sum(Receipt.amount)).where(
            Receipt.product_id == product.id,
            Receipt.day >= net.since,
            Receipt.day <= net.last,
            Receipt.qty > 0,
            Receipt.amount > 0,
        )
    ).one()
    price = amount / qty if qty else None
    raised: dict[UUID, list[Line]] = dict(net.recipes)
    dishes = []
    changed = []
    for parent, card in sorted(net.recipes.items(), key=lambda x: str(x[0])):
        old = sum((ln.gross_qty for ln in card if ln.product_id == product.id), Decimal(0))
        if not old:
            continue
        if parent in net.items:
            name, code, semi = net.items[parent].name, net.items[parent].code, False
        elif parent in net.semis:
            name, code, semi = net.semis[parent].name, net.semis[parent].code, True
        else:
            continue
        if f.period_to is not None and net.versions[parent] > f.period_to:
            changed.append(name)  # the card changed after the finding's period: not raised twice (p. 3)
            continue
        new = (old * (1 + raise_by)).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
        if new == old:
            continue
        factor = new / old
        raised[parent] = [
            replace(ln, gross_qty=ln.gross_qty * factor) if ln.product_id == product.id else ln for ln in card
        ]
        cost = (new - old) * price if price is not None else None
        dishes.append(
            {
                "name": name,
                "code": code,
                "semi": semi,
                "old": plain(old),
                "new": plain(new),
                "cost": _rub(cost) if cost is not None else None,
            }
        )
    if not dishes:
        return None
    # The month: every dish sold, through its semi-products too (p. 4) — the product per portion with the new
    # cards less with the old ones, at the network's price.
    month = None
    if price is not None:
        per_month = MONTH_DAYS / WINDOW_DAYS
        extra = sum(
            (
                (
                    explode(i, n, raised).get(product.id, Decimal(0))
                    - explode(i, n, net.recipes).get(product.id, Decimal(0))
                )
                for i, n in net.sold.items()
                if i in net.recipes
            ),
            Decimal(0),
        )
        month = _rub(extra * price * per_month)
    dishes.sort(key=lambda d: (d["semi"], d["name"], d["code"]))
    restaurants = ev.get("restaurants") or {}
    return NoteDraft(
        agent=Agent.RECIPE_UPDATE,
        audience=Audience.HQ,
        restaurant_id=None,
        key=f"recipe_update:{f.key}",
        for_date=f.period_to or net.last,
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
            "changed": sorted(changed),
            "month_cost": month,
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
    checked = [f for f in found if f.checked]
    if not checked:
        return []
    net = _network(session, today)
    return [d for f in checked if (d := _draft(session, net, f)) is not None]
