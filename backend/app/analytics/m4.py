"""M4. Stock counts: what makes a count say something other than what happened (docs/12, M4).

- Write-offs right before counts: most of a restaurant's write-offs (in rubles) are dated in the
  `M4_PRE_DAYS` days before its counts — shortages are closed with write-off acts, real losses are not seen.
- Mixed-up products at the last count: one product shows a surplus against the books while a product of the
  same category shows a shortage of about the same quantity — counted under the wrong name.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from uuid import UUID

from app.analytics.costs import CostBook
from app.analytics.drafts import Draft, dmy, pct
from app.analytics.facts import CountRow, Facts
from app.analytics.params import DEFAULT, EngineParams


def detect(facts: Facts, costs: CostBook, cfg: EngineParams = DEFAULT) -> list[Draft]:
    return _pre_count(facts, costs, cfg) + _mixed_up(facts, cfg)


def _pre_count(facts: Facts, costs: CostBook, cfg: EngineParams) -> list[Draft]:
    count_days: dict[UUID, list[date]] = defaultdict(list)
    for d in sorted({(c.restaurant, c.day) for c in facts.counts}):
        count_days[d[0]].append(d[1])
    drafts = []
    for restaurant, days in count_days.items():
        if len(days) < 2:
            continue
        since, last = days[0], days[-1]
        total = before = Decimal(0)
        for w in facts.write_offs:
            if w.restaurant != restaurant or not since < w.day <= last:
                continue
            cost = costs.cost(restaurant, w.product, since + timedelta(days=1), last)
            if cost is None:
                continue
            value = w.qty * cost.rub_per_unit
            total += value
            if any(1 <= (c - w.day).days <= cfg.M4_PRE_DAYS for c in days[1:]):
                before += value
        if total <= 0:
            continue
        share = before / total
        # Write-offs spread evenly over the days would put this share in the days before the counts.
        expected = Decimal(cfg.M4_PRE_DAYS * (len(days) - 1)) / (last - since).days
        if share < cfg.M4_PRE_SHARE or share < cfg.M4_PRE_TIMES * expected:
            continue
        code = facts.restaurants[restaurant]
        drafts.append(
            Draft(
                key=f"M4:{code}:pre-count",
                module="M4",
                kind="problem",
                process="inventory",
                restaurant=restaurant,
                title=f"{pct(share, 0)} списаний оформлено за {cfg.M4_PRE_DAYS} дня до инвентаризации",
                headline=(
                    f"С {dmy(since + timedelta(days=1))} по {dmy(last)} {pct(share, 0)} списаний (в рублях) "
                    f"оформлено в последние {cfg.M4_PRE_DAYS} дня перед пересчетом, хотя при списаниях "
                    f"в день порчи было бы ≈ {pct(expected, 0)}. Так обычно закрывают недостачи, и реальные "
                    "потери не видны"
                ),
                effect_rub_month=None,
                effect_note="искажает потери ресторана",
                confidence="high" if len(days) >= 3 else "medium",
                period_from=since + timedelta(days=1),
                period_to=last,
                actions=[
                    "Оформлять списания в день, когда продукт испорчен",
                    "Выборочно сверить акты с фото",
                ],
                evidence={
                    "kind": "pre_count",
                    "counts": [d.isoformat() for d in days],
                    "days_before": cfg.M4_PRE_DAYS,
                    "share": str(share.quantize(Decimal("0.0001"))),
                    "expected": str(expected.quantize(Decimal("0.0001"))),
                    "write_offs_rub": str(total.quantize(Decimal("0.01"))),
                    "before_rub": str(before.quantize(Decimal("0.01"))),
                },
            )
        )
    return drafts


def _mixed_up(facts: Facts, cfg: EngineParams) -> list[Draft]:
    """At each restaurant's last count: a product off its books upwards, and a product of the same category
    off by about the same amount downwards — beyond what each usually differs (median of earlier counts)."""
    by_restaurant: dict[UUID, dict[date, list[CountRow]]] = defaultdict(lambda: defaultdict(list))
    for c in facts.counts:
        if c.book is not None and c.book > 0:
            by_restaurant[c.restaurant][c.day].append(c)
    drafts = []
    for restaurant, by_day in by_restaurant.items():
        days = sorted(by_day)
        if len(days) < 3:
            continue
        day = days[-1]
        usual: dict[UUID, list[Decimal]] = defaultdict(list)
        # The first count only opens the books (nothing to differ from yet): the usual comes from the others.
        for d in days[1:-1]:
            for c in by_day[d]:
                usual[c.product].append((c.actual - (c.book or Decimal(0))) / (c.book or Decimal(1)))
        rows = {c.product: c for c in by_day[day] if usual.get(c.product)}

        offs = {p: _off(c, usual[p]) for p, c in rows.items()}
        used: set[UUID] = set()
        surpluses = sorted(
            (
                p
                for p, c in rows.items()
                if c.actual > (c.book or 0) and offs[p] >= cfg.M4_SORT_SHARE * (c.book or 0)
            ),
            key=lambda p: -offs[p],
        )
        for plus in surpluses:
            info = facts.products[plus]
            size = offs[plus]
            candidates = [
                p
                for p, o in offs.items()
                if p not in used
                and p != plus
                and o < 0
                and facts.products[p].category == info.category
                and facts.products[p].unit == info.unit
                and abs(-o - size) <= cfg.M4_SORT_MATCH * size
            ]
            if not candidates:
                continue
            minus = min(candidates, key=lambda p: abs(-offs[p] - size))
            used |= {plus, minus}
            drafts.append(_mixed_up_draft(facts, restaurant, day, rows, offs, plus, minus))
    return drafts


def _off(c: CountRow, usual: list[Decimal]) -> Decimal:
    """How far this count is from the product's usual difference to the books, in base units."""
    book = c.book or Decimal(0)
    return (c.actual - book) - Decimal(median(usual)) * book


def _mixed_up_draft(
    facts: Facts,
    restaurant: UUID,
    day: date,
    rows: dict[UUID, CountRow],
    offs: dict[UUID, Decimal],
    plus: UUID,
    minus: UUID,
) -> Draft:
    a, b = sorted([plus, minus], key=lambda p: facts.products[p].code)
    code = facts.restaurants[restaurant]
    info = facts.products[plus]
    unit = {"kg": "кг", "l": "л", "pcs": "шт"}.get(info.unit, info.unit)

    def signed(value: Decimal) -> str:
        return f"{value:+.2f}".replace(".", ",").replace("-", "−")

    def diff(p: UUID) -> Decimal:
        return rows[p].actual - (rows[p].book or Decimal(0))

    name = {p: facts.products[p].name.lower() for p in (plus, minus)}
    return Draft(
        key=f"M4:{code}:{facts.products[a].code}-{facts.products[b].code}",
        module="M4",
        kind="problem",
        process="inventory",
        restaurant=restaurant,
        title=f"Пересорт: {facts.products[a].name.lower()} и {facts.products[b].name.lower()}",
        headline=(
            f"На пересчете {dmy(day)} {name[plus]} {signed(diff(plus))} {unit} к учету, а {name[minus]} "
            f"{signed(diff(minus))} {unit}. Сверх обычного расхождения излишек одного "
            f"({signed(offs[plus])} {unit}) почти равен недостаче другого ({signed(offs[minus])} {unit}) — "
            "товары, вероятно, перепутали"
        ),
        effect_rub_month=None,
        effect_note="искажает остатки и потери обоих товаров",
        confidence="medium",
        period_from=day,
        period_to=day,
        actions=["Пересчитать оба товара заново", "Разделить хранение и подписать контейнеры"],
        evidence={
            "kind": "mixed_up",
            "day": day.isoformat(),
            "products": {
                facts.products[p].code: {
                    "book": str((rows[p].book or Decimal(0)).quantize(Decimal("0.001"))),
                    "actual": str(rows[p].actual.quantize(Decimal("0.001"))),
                    "off_usual": str(offs[p].quantize(Decimal("0.001"))),
                }
                for p in (plus, minus)
            },
        },
    )
