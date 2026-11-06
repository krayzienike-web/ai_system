"""Linked findings: findings with one cause are told as one story (stage 6.5; docs/12).

The engine sometimes sees one cause from several sides: cream bought for 16 days spoils (M6 overstock) and
shows up in the write-offs (M5); salmon grew 40 % for the network (M3) and the dish with it costs more (M2).
Each finding stays as it is — its own numbers, check and task — but carries the story's key and title, so the
screens show them together and the money is not counted twice: a story's sum is its largest finding's.

The rules (each pair has to share its scope: one restaurant, or the whole network):
- **supply** — overstock and write-offs of the same product in the same restaurant: bought more than is used;
- **price** — a network-wide price rise of a product and the food cost of the dishes it drives;
- **supplier** — overuse against the recipe and a dearer purchase of the same product in the same restaurant;
- **receipts** — usage below the recipe and a book stock going negative for the same product in the same
  restaurant: invoices are missing.
"""

from collections import defaultdict
from decimal import Decimal

from app.analytics.drafts import Draft
from app.analytics.facts import Facts


def _product(d: Draft) -> str | None:
    p = d.evidence.get("product")
    return p if isinstance(p, str) else None


def _scope(d: Draft, facts: Facts) -> str:
    return facts.restaurants.get(d.restaurant, "net") if d.restaurant else "net"


def _top_ingredient(d: Draft) -> str | None:
    """The ingredient that made a dish's portion dearer the most (M2 food cost evidence)."""
    best: tuple[Decimal, str] | None = None
    for i in d.evidence.get("ingredients") or []:
        if i.get("price_before") is None:
            continue
        grew = Decimal(i["qty"]) * (Decimal(i["price"]) - Decimal(i["price_before"]))
        if grew > 0 and (best is None or grew > best[0]):
            best = (grew, i["product"])
    return best[1] if best else None


def _role(d: Draft) -> tuple[str, str] | None:
    """(rule, side) a finding can play in a story, by module and kind."""
    kind = d.evidence.get("kind")
    if d.module == "M6" and kind == "overstock":
        return "supply", "cause"
    if d.module == "M5":
        return "supply", "effect"
    if d.module == "M3" and kind == "growth":
        return "price", "cause"
    if d.module == "M1" and d.restaurant is not None and not d.key.endswith(":under"):
        return "supplier", "effect"
    if d.module == "M3" and d.restaurant is not None:
        return "supplier", "cause"
    if d.module == "M1" and d.key.endswith(":under"):
        return "receipts", "effect"
    if d.module == "M7" and (kind == "negative" or d.key.endswith(":negative")):
        return "receipts", "cause"
    return None


TITLES = {
    "supply": "Закупают больше, чем успевают использовать: {name}",
    "price": "Подорожал {name}: вырос фудкост блюд",
    "supplier": "Перерасход и дорогая закупка: {name}",
    "receipts": "Не все накладные загружены: {name}",
}


def link(drafts: list[Draft], facts: Facts) -> None:
    """Give the findings of one cause a common `story_key` and `story_title` (in place)."""
    by_code = {p.code: p for p in facts.products.values()}
    groups: dict[tuple[str, str, str], list[Draft]] = defaultdict(list)
    for d in drafts:
        role = _role(d)
        product = _product(d)
        if role is not None and product is not None:
            groups[(role[0], _scope(d, facts), product)].append(d)
    # The dishes a network-wide price rise made dearer join that rise's story.
    for d in drafts:
        if d.module == "M2" and d.restaurant is None and "ingredients" in d.evidence:
            top = _top_ingredient(d)
            if top and ("price", "net", top) in groups:
                groups[("price", "net", top)].append(d)
    for (rule, scope, product), members in groups.items():
        sides = {r[1] for m in members if (r := _role(m)) is not None}
        if len(members) < 2 or (rule != "price" and sides != {"cause", "effect"}):
            continue
        info = by_code.get(product)
        name = info.name if info else product
        for m in members:
            m.story_key = f"{rule}:{scope}:{product}"
            m.story_title = TITLES[rule].format(name=name.lower() if rule == "price" else name)


def story_sum(effects: list[Decimal | None]) -> Decimal | None:
    """One cause, one sum: the largest of the story's findings (they count the same money)."""
    known = [e for e in effects if e is not None]
    return max(known) if known else None
