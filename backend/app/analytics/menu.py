"""Menu engineering: popularity × margin of every dish of the menu, by category (docs/12 «Меню-инжиниринг»).

The engine's M2 raises a finding only for the far corners (a popular dish earning little, a rare one earning a
lot); this is the whole matrix the HQ looks at when it plans the next menu. The same numbers as M2: the
network's purchase prices of the last `M2_WINDOW_DAYS` up to the latest invoice, the recipe cards in force on
that day, the menu price. Within a category (Kasavana and Smith):
- popular — at least `M2_ME_POPULARITY` of an equal share of the category's portions;
- high margin — the margin per portion at or above the category's average weighted by portions.
Star: popular and high; plowhorse: popular and low; puzzle: rare and high; dog: rare and low.
Popularity may be one restaurant's; the prices and the cards are the network's (menu prices are).
A dish without a price, a card, a price of an ingredient or a sale in the window is listed as not counted.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow
from app.analytics.m2 import portion_cost, unit_prices
from app.analytics.params import DEFAULT, EngineParams
from app.catalog.models import MenuItem, Product, RecipeLine
from app.catalog.recipes import Line, explode, lines_on
from app.operations.models import Receipt, Sale

Quadrant = Literal["star", "plowhorse", "puzzle", "dog"]
MONTH_DAYS = Decimal(30)
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Dish:
    code: str
    name: str
    price: Decimal
    cost: Decimal
    margin: Decimal
    food_cost: Decimal  # cost / price
    portions_month: Decimal
    share: Decimal  # of the category's portions
    quadrant: Quadrant


@dataclass(frozen=True)
class Category:
    name: str
    margin: Decimal  # average per portion, weighted by portions
    fair_share: Decimal  # an equal share: 1 / dishes
    popular_from: Decimal  # the share from which a dish is popular
    dishes: list[Dish]


@dataclass(frozen=True)
class Matrix:
    since: date | None
    until: date | None
    categories: list[Category] = field(default_factory=list)
    not_counted: list[str] = field(
        default_factory=list
    )  # dish names: no price, card, ingredient price or sale


def _q(v: Decimal, places: Decimal = CENT) -> Decimal:
    return v.quantize(places, rounding=ROUND_HALF_UP)


def matrix(facts: Facts, cfg: EngineParams = DEFAULT, restaurant: UUID | None = None) -> Matrix:
    if not facts.receipts:
        return Matrix(None, None)
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    prices = unit_prices(facts, start, end)
    recipes = lines_on(facts.recipe_lines, end)
    portions: dict[UUID, Decimal] = defaultdict(Decimal)
    for s in facts.sales:
        if start <= s.day <= end and (restaurant is None or s.restaurant == restaurant):
            portions[s.menu_item] += s.qty
    per_month = MONTH_DAYS / cfg.M2_WINDOW_DAYS
    rows: dict[str, list[tuple[UUID, Decimal, Decimal]]] = defaultdict(list)  # item, cost, portions
    missing = []
    for item, info in sorted(facts.menu.items(), key=lambda x: x[1].name):
        cost = (
            portion_cost(explode(item, Decimal(1), recipes), prices)
            if item in recipes and info.price and info.price > 0
            else None
        )
        if cost is None or portions[item] <= 0:
            missing.append(info.name)
            continue
        rows[info.category or "Без категории"].append((item, cost, portions[item]))
    categories = []
    for name, dishes in sorted(rows.items()):
        total = sum((q for _, _, q in dishes), Decimal(0))
        prices_of = {i: facts.menu[i].price or Decimal(0) for i, _, _ in dishes}
        avg = sum(((prices_of[i] - c) * q for i, c, q in dishes), Decimal(0)) / total
        fair = Decimal(1) / len(dishes)
        out = []
        for item, cost, qty in dishes:
            price, share = prices_of[item], qty / total
            margin = price - cost
            popular, high = share >= cfg.M2_ME_POPULARITY * fair, margin >= avg
            quadrant: Quadrant = (
                ("star" if high else "plowhorse") if popular else ("puzzle" if high else "dog")
            )
            out.append(
                Dish(
                    code=facts.menu[item].code,
                    name=facts.menu[item].name,
                    price=_q(price),
                    cost=_q(cost),
                    margin=_q(margin),
                    food_cost=_q(cost / price, Decimal("0.0001")),
                    portions_month=_q(qty * per_month, Decimal("0.1")),
                    share=_q(share, Decimal("0.0001")),
                    quadrant=quadrant,
                )
            )
        out.sort(key=lambda d: (-d.share, d.name))
        categories.append(
            Category(
                name=name,
                margin=_q(avg),
                fair_share=_q(fair, Decimal("0.0001")),
                popular_from=_q(cfg.M2_ME_POPULARITY * fair, Decimal("0.0001")),
                dishes=out,
            )
        )
    return Matrix(start, end, categories, missing)


def load(session: Session, cfg: EngineParams = DEFAULT) -> Facts:
    """Only what the matrix reads: the menu, the cards, the products and the window's invoices and sales —
    not the network's whole history (backend review of stage 11, p. 8)."""
    end = session.execute(select(func.max(Receipt.day))).scalar_one()
    if end is None:
        return Facts()
    start = end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    products = {
        p.id: ProductInfo(p.code, p.name, p.category, p.base_unit, p.shelf_life_days, p.is_semi)
        for p in session.execute(select(Product)).scalars()
    }
    items = {
        m.id: MenuInfo(m.code, m.name, m.category, m.price)
        for m in session.execute(select(MenuItem)).scalars()
    }
    lines = [
        Line(parent, r.product_id, r.gross_qty, r.valid_from)
        for r in session.execute(select(RecipeLine).where(RecipeLine.valid_from <= end)).scalars()
        if (parent := r.menu_item_id or r.semi_product_id) is not None
    ]
    receipts = [
        ReceiptRow(*row)
        for row in session.execute(
            select(
                Receipt.restaurant_id,
                Receipt.day,
                Receipt.product_id,
                Receipt.supplier_id,
                Receipt.qty,
                Receipt.amount,
            ).where(Receipt.day >= start, Receipt.day <= end)
        ).all()
    ]
    sales = [
        SaleRow(r, d, i, q, rev)
        for r, d, i, q, rev in session.execute(
            select(Sale.restaurant_id, Sale.day, Sale.menu_item_id, Sale.qty, Sale.revenue).where(
                Sale.day >= start, Sale.day <= end
            )
        ).all()
    ]
    return Facts(products=products, menu=items, recipe_lines=lines, sales=sales, receipts=receipts)
