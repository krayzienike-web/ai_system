"""What a check measures and how (stage 7; docs/05, «Замер» and «Эксперименты в пилоте на 3 ресторанах»).

The metric follows the finding the check is made of; three designs: the test restaurant against similar
restaurants, the product against other products of its category in the same restaurant, before and after
without a control (weak evidence). For each design the draft shows the smallest effect the check would see.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.analytics.facts import Facts
from app.analytics.measure import Spec, Unit, mde_by_weeks
from app.analytics.usage import Usage
from app.insights.models import Finding

MIN_BASELINE_DAYS = 28
DESIGNS = {
    "restaurants": "Ресторан против похожих ресторанов",
    "items": "Контроль внутри ресторана: другие товары категории",
    "before_after": "До и после, без сравнения",
}


@dataclass(frozen=True)
class Option:
    design: str
    title: str
    available: bool
    note: str
    weak: bool
    mde_by_weeks: dict[int, Decimal]  # the smallest effect it would see, for each length the wizard offers
    control_products: list[UUID]

    def mde(self, weeks: int) -> Decimal | None:
        return self.mde_by_weeks.get(weeks)


def spec_for(finding: Finding, product_ids: dict[str, UUID]) -> Spec | None:
    """What a check of this finding measures (docs/05, table «Метрика»); None — a check cannot measure it."""
    ev = finding.evidence or {}
    product = product_ids.get(str(ev.get("product"))) if ev.get("product") else None
    kind = ev.get("kind")
    if finding.restaurant_id is None:
        return None
    if finding.module == "M1" and product and not (finding.key or "").endswith(":under"):
        return Spec("overuse", product)
    if finding.module == "M5" and product:
        return Spec("writeoffs", product)
    if finding.module == "M6" and kind == "overstock" and product:
        return Spec("writeoffs", product)  # what lies over its shelf life ends in the write-offs
    if finding.module == "M3" and product:
        return Spec("price", product)
    if finding.module == "M8" and kind in ("discounts", "voids"):
        return Spec(str(kind), cashier=ev.get("cashier"))
    return None


def baseline(starts_on: date, ends_on: date) -> tuple[date, date]:
    """The period before a check: as long as the check, but not shorter than four weeks."""
    days = max((ends_on - starts_on).days, MIN_BASELINE_DAYS)
    return starts_on - timedelta(days=days), starts_on - timedelta(days=1)


def seed(experiment_id: UUID) -> int:
    return experiment_id.int % (2**32)


WEEKS = (2, 4, 6)  # the lengths the wizard offers (experiments.service.DURATIONS)
PRODUCT_KINDS = ("overuse", "writeoffs")  # «items» compares shares of products; a price is not a share (p. 8)
CASHIER_KINDS = ("discounts", "voids")


def units(
    spec: Spec, design: str, test: UUID, controls: list[UUID], items: list[UUID]
) -> tuple[Unit, list[Unit]]:
    """The test and the control of a design. A cashier's metric: other restaurants as a whole, or the same
    restaurant's other cashiers — the cashier is not in another restaurant (code review of stage 7, p. 2)."""
    me = Unit(test)
    if design == "before_after":
        return me, []
    if design == "items":
        if spec.kind in CASHIER_KINDS:
            return me, [Unit(test, others=True)]
        return me, [Unit(test, frozenset(items))]
    return me, [Unit(c, whole=True) for c in controls]


def options(
    facts: Facts,
    spec: Spec,
    test: UUID,
    controls: list[UUID],
    starts_on: date,
    ends_on: date,
    salt: int,
    usage: Usage | None = None,
) -> list[Option]:
    """The three designs for a check, each with whether it fits (it has its comparison: restaurants, other
    products or cashiers) and the smallest effect it would see for each length — empty when the data before
    the check cannot tell (the wizard says «не оценить»; a check with nothing to compare at its end is closed
    as such, never left running)."""
    usage = usage or Usage(facts)
    before = baseline(starts_on, ends_on)

    def mde(design: str, items: list[UUID]) -> dict[int, Decimal]:
        me, others = units(spec, design, test, controls, items)
        return mde_by_weeks(facts, usage, spec, design, me, others, before, salt, WEEKS) or {}

    out = []
    by_restaurants = mde("restaurants", []) if controls else {}
    out.append(
        Option(
            "restaurants",
            DESIGNS["restaurants"],
            bool(controls),
            ("сравниваем с похожими ресторанами сети" + (" (весь ресторан)" if spec.cashier else ""))
            if controls
            else "нет ресторанов для сравнения",
            False,
            by_restaurants,
            [],
        )
    )
    peers: list[UUID] = []
    if spec.kind in PRODUCT_KINDS and spec.product in facts.products:
        category = facts.products[spec.product].category
        used = {p for (r, p) in usage.by_day if r == test}
        peers = sorted(
            (
                p
                for p, info in facts.products.items()
                if p != spec.product and info.category == category and not info.is_semi and p in used
            ),
            key=lambda p: facts.products[p].code,
        )
    items_fit = bool(peers) or (spec.kind in CASHIER_KINDS and bool(spec.cashier))
    if spec.kind in CASHIER_KINDS and spec.cashier:
        by_items = mde("items", [])
        note = "сравниваем с другими кассирами этого ресторана"
    elif peers:
        by_items = mde("items", peers)
        note = "мера — только для этого товара; сравниваем с: " + ", ".join(
            facts.products[p].name.lower() for p in peers[:4]
        )
    else:
        by_items = {}
        note = "сравнить внутри ресторана не с чем" if spec.kind not in ("price",) else "для цены не подходит"
    out.append(Option("items", DESIGNS["items"], items_fit, note, False, by_items, peers))
    alone = mde("before_after", [])
    out.append(
        Option(
            "before_after",
            DESIGNS["before_after"],
            True,
            "только до и после в этом ресторане — слабое доказательство",
            True,
            alone,
            [],
        )
    )
    return out


def recommended(opts: list[Option], expected: Decimal, weeks: int) -> str:
    """The design that would see the expected effect at `weeks` with the fewest assumptions (restaurants, then
    items); none would — the one that sees the smallest effect (the wizard then warns, docs/05)."""
    fit = [o for o in opts if o.available and not o.weak and o.mde(weeks) is not None]
    for o in fit:
        if (o.mde(weeks) or Decimal(0)) <= expected:
            return o.design
    if fit:
        return min(fit, key=lambda o: o.mde(weeks) or Decimal(0)).design
    return "before_after"
