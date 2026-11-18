"""№ 14. Menu prices after purchases grew (docs/07 «ИИ-агенты», ADR 0010; stage 12).

Two reasons: the network pays noticeably more for a product (an open, checked M3 finding «Цена выросла по всей
сети», `M3:net:<code>:growth`), or a dish's recipe card changed in the last `CARD_DAYS`. For every dish the
reason touches (through semi-products too), the cost of a portion now and before with the same windows and
prices as the engine's M2 (the network's purchases over the last `M2_WINDOW_DAYS`, and the same window
`M2_COMPARE_DAYS` earlier; the cards in force at the end of each), so the note and the finding «Фудкост выше
целевого» never disagree. Listed: dishes whose food cost was within the target (the HQ's norms, by menu
category) and is above it now; how many were above it already is said in a line. For each — how to come back
to the target: - the menu price (rounded up to `M2_PRICE_STEP`, as M2 suggests);
- or less of the product in a portion, when cutting at most `MAX_CUT` of it is enough (to 0.001, down).
And the margin the network loses a month on the window's sales. The HQ decides; the price is changed in the
till system: «Скопировать записку», «Отправлено».
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.analytics import menu, params
from app.analytics.facts import Facts, ReceiptRow
from app.analytics.m2 import portion_cost, suggested_price, unit_prices
from app.analytics.params import DEFAULT, EngineParams
from app.catalog.recipes import Line, explode, lines_on
from app.insights.models import Finding, FindingStatus
from app.norms.service import Norms, load_norms
from app.operations.models import Receipt
from app.tenancy.models import Restaurant

CARD_DAYS = 28  # a card that changed this recently is news
MAX_CUT = Decimal("0.25")  # a portion is not cut by more than a quarter of the product
QTY = Decimal("0.001")
MONTH_DAYS = Decimal(30)
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


def _rub(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(v: Decimal) -> str:
    return str((v * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Window:
    end: date
    now: dict[UUID, Decimal]  # the network's price of each product, the last window
    before: dict[UUID, Decimal]  # … the same window a quarter earlier
    cards: dict[UUID, list[Line]]  # in force at the end of the last window
    cards_before: dict[UUID, list[Line]]
    portions_month: dict[UUID, Decimal]  # each dish's portions a month over the last window
    price: dict[UUID, Decimal]  # the menu price, or the till's when the menu has none — as M2 (review, p. 6)


def window(facts: Facts, cfg: EngineParams = DEFAULT) -> Window | None:
    if not facts.receipts:
        return None
    end = max(r.day for r in facts.receipts)
    start = end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    before_end = end - timedelta(days=cfg.M2_COMPARE_DAYS)
    before_start = before_end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    portions: dict[UUID, Decimal] = defaultdict(Decimal)
    revenue: dict[UUID, Decimal] = defaultdict(Decimal)
    for s in facts.sales:
        if start <= s.day <= end:
            portions[s.menu_item] += s.qty
            revenue[s.menu_item] += s.revenue
    per_month = MONTH_DAYS / cfg.M2_WINDOW_DAYS
    return Window(
        end=end,
        now=unit_prices(facts, start, end),
        before=unit_prices(facts, before_start, before_end),
        cards=lines_on(facts.recipe_lines, end),
        cards_before=lines_on(facts.recipe_lines, before_end),
        portions_month={i: q * per_month for i, q in portions.items()},
        price={
            i: p
            for i, info in facts.menu.items()
            if (p := info.price or (revenue[i] / portions[i] if portions[i] else Decimal(0))) > 0
        },
    )


def dishes(
    facts: Facts, w: Window, norms: Norms, items: set[UUID], product: UUID | None, cfg: EngineParams = DEFAULT
) -> tuple[list[dict[str, object]], int]:
    """The dishes of `items` pushed above the target, and how many of them were above it already. `product` —
    the product that grew: the portion is cut in it; None (a new card) — no portion to propose."""
    listed: list[dict[str, object]] = []
    already = 0
    for item in sorted(items, key=lambda i: (facts.menu[i].name, facts.menu[i].code)):
        info = facts.menu[item]
        price = w.price.get(item)
        if item not in w.cards or price is None or not w.portions_month.get(item):
            continue
        need = explode(item, Decimal(1), w.cards)
        cost = portion_cost(need, w.now)
        need_before = explode(item, Decimal(1), w.cards_before) if item in w.cards_before else {}
        cost_before = portion_cost(need_before, w.before)
        if cost is None or cost_before is None:
            continue
        target = norms.food_cost_target(info.category) / 100
        if cost / price <= target:
            continue
        if cost_before / price > target:
            already += 1
            continue
        over = cost - target * price
        cut = None
        if product is not None and need.get(product):
            q = need[product]
            new_q = (q - over / w.now[product]).quantize(QTY, rounding=ROUND_DOWN)
            if new_q > 0 and q - new_q <= MAX_CUT * q:
                cut = {"old": str(q.quantize(QTY)), "new": str(new_q)}
        listed.append(
            {
                "name": info.name,
                "code": info.code,
                "price": _rub(price),
                "cost": _rub(cost),
                "cost_before": _rub(cost_before),
                "food_cost_pct": _pct(cost / price),
                "food_cost_before_pct": _pct(cost_before / price),
                "target_pct": _pct(target),
                "new_price": _rub(suggested_price(cost, target, cfg)),
                "cut": cut,
                "lost_month": _rub((cost - cost_before) * w.portions_month[item]),
            }
        )
    return listed, already


def load(session: Session, cfg: EngineParams = DEFAULT) -> Facts:
    """What the matrix of «Меню» reads, and the network's purchases of the window a quarter earlier."""
    facts = menu.load(session, cfg)
    if not facts.receipts:
        return facts
    end = max(r.day for r in facts.receipts)
    before_end = end - timedelta(days=cfg.M2_COMPARE_DAYS)
    before_start = before_end - timedelta(days=cfg.M2_WINDOW_DAYS - 1)
    facts.receipts += [
        ReceiptRow(*row)
        for row in session.execute(
            select(
                Receipt.restaurant_id,
                Receipt.day,
                Receipt.product_id,
                Receipt.supplier_id,
                Receipt.qty,
                Receipt.amount,
            ).where(Receipt.day >= before_start, Receipt.day <= before_end)
        ).all()
    ]
    return facts


def _using(w: Window, facts: Facts, product: UUID) -> set[UUID]:
    return {i for i in facts.menu if i in w.cards and product in explode(i, Decimal(1), w.cards)}


def changed_on(item: UUID, cards: dict[UUID, list[Line]]) -> date:
    """The latest start of a card in the dish's tree: its own and its semi-products' (review, p. 8)."""
    latest, seen, todo = date.min, set(), [item]
    while todo:
        node = todo.pop()
        if node in seen or node not in cards:
            continue
        seen.add(node)
        latest = max(latest, cards[node][0].valid_from)
        todo += [ln.product_id for ln in cards[node]]
    return latest


def _growth(session: Session) -> list[Finding]:
    rows = session.execute(
        select(Finding)
        .where(
            Finding.module == "M3",
            Finding.restaurant_id.is_(None),
            Finding.status.in_(OPEN),
            Finding.key.like("M3:net:%:growth"),
        )
        .order_by(Finding.key)
    ).scalars()
    return [f for f in rows if f.checked]


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    growth = _growth(session)
    cfg = params.load(session)
    facts = load(session, cfg)
    w = window(facts, cfg)
    if w is None:
        return []
    norms = load_norms(session)
    priced: set[str] = set()  # dishes of the price notes: not repeated in a card's note (review, p. 10)
    by_code = {info.code: pid for pid, info in facts.products.items()}
    out = []
    for f in growth:
        ev = f.evidence or {}
        pid = by_code.get(ev.get("product", ""))
        if pid is None or pid not in w.now or pid not in w.before:
            continue
        listed, already = dishes(facts, w, norms, _using(w, facts, pid), pid, cfg)
        if not listed:
            continue
        priced |= {str(d["code"]) for d in listed}
        info = facts.products[pid]
        out.append(
            NoteDraft(
                agent=Agent.MENU_PRICE,
                audience=Audience.HQ,
                restaurant_id=None,
                key=f"menu_price:{f.key}",
                for_date=w.end,
                facts={
                    "reason": "price",
                    "product": info.name,
                    "unit": info.unit,
                    "price": _rub(w.now[pid]),
                    "price_before": _rub(w.before[pid]),
                    "growth_pct": _pct(w.now[pid] / w.before[pid] - 1),
                    "dishes": listed,
                    "already": already,
                },
                proposal={"action": "claim"},
            )
        )
    # New cards: the dishes whose card started within `CARD_DAYS` up to the end of the window, by the day.
    changed: dict[date, set[UUID]] = defaultdict(set)
    for item, dish in facts.menu.items():
        day = changed_on(item, w.cards) if item in w.cards else date.min
        if w.end - timedelta(days=CARD_DAYS) < day <= w.end and dish.code not in priced:
            changed[day].add(item)
    for day, items in sorted(changed.items()):
        listed, already = dishes(facts, w, norms, items, None, cfg)
        if not listed:
            continue
        out.append(
            NoteDraft(
                agent=Agent.MENU_PRICE,
                audience=Audience.HQ,
                restaurant_id=None,
                key=f"menu_price:card:{day.isoformat()}",
                for_date=day,
                facts={"reason": "card", "since": day.isoformat(), "dishes": listed, "already": already},
                proposal={"action": "claim"},
            )
        )
    return out
