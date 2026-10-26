"""M1. Recipe execution: actual usage between two stock counts against what the recipes say.

U = A − T − W, where A = opening stock + purchases + transfers in − transfers out − closing stock (counted),
T = theoretical usage (sales × recipes), W = documented write-offs. U% = U / T, U₽ = U × unit cost.
See docs/02-analytics-spec.md (M1) and docs/12-analytics-engine.md for the decision rules.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from uuid import UUID

from app.analytics import params
from app.analytics.costs import CostBook
from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts
from app.analytics.stats import med, robust_z
from app.analytics.usage import Usage
from app.norms.service import Norms

ACTIONS_RESTAURANT = [
    "Проверить вес порций на раздаче: контрольное взвешивание 10 блюд",
    "Сверить выход при обработке с техкартой",
    "Проверить, все ли списания оформлены",
]
ACTIONS_NETWORK = [
    "Провести контрольную проработку блюда и обновить техкарту",
    "Разослать новую техкарту во все рестораны",
]


@dataclass(frozen=True)
class M1Row:
    restaurant: UUID
    product: UUID
    start: date  # day of the opening count (its stock is the starting point)
    end: date  # day of the closing count
    theory: Decimal
    actual: Decimal
    write_off: Decimal
    unit_cost: Decimal | None

    @property
    def unexplained(self) -> Decimal:
        return self.actual - self.theory - self.write_off

    @property
    def share(self) -> Decimal:
        return self.unexplained / self.theory

    @property
    def rub(self) -> Decimal | None:
        return None if self.unit_cost is None else self.unexplained * self.unit_cost

    @property
    def first_day(self) -> date:
        return self.start + timedelta(days=1)


def rows(facts: Facts, usage: Usage, costs: CostBook) -> list[M1Row]:
    counts: dict[UUID, dict[date, dict[UUID, Decimal]]] = defaultdict(lambda: defaultdict(dict))
    for c in facts.counts:
        counts[c.restaurant][c.day][c.product] = c.actual
    moves: dict[tuple[UUID, UUID], list[tuple[date, Decimal]]] = defaultdict(list)
    for r in facts.receipts:
        moves[(r.restaurant, r.product)].append((r.day, r.qty))
    for t in facts.transfers:
        moves[(t.receiver, t.product)].append((t.day, t.qty))
        moves[(t.sender, t.product)].append((t.day, -t.qty))
    written: dict[tuple[UUID, UUID], list[tuple[date, Decimal]]] = defaultdict(list)
    for w in facts.write_offs:
        written[(w.restaurant, w.product)].append((w.day, w.qty))

    def between(items: list[tuple[date, Decimal]], start: date, end: date) -> Decimal:
        return sum((q for d, q in items if start < d <= end), Decimal(0))

    out = []
    for restaurant, by_day in counts.items():
        days = sorted(by_day)
        for start, end in pairwise(days):
            if (end - start).days < params.M1_MIN_THEORY_DAYS:
                continue
            for product in by_day[start].keys() & by_day[end].keys():
                info = facts.products.get(product)
                if info is None or info.is_semi:
                    continue
                theory = usage.total(restaurant, product, start + timedelta(days=1), end)
                if theory <= 0:
                    continue
                key = (restaurant, product)
                actual = by_day[start][product] + between(moves[key], start, end) - by_day[end][product]
                cost = costs.cost(restaurant, product, start + timedelta(days=1), end)
                out.append(
                    M1Row(
                        restaurant,
                        product,
                        start,
                        end,
                        theory,
                        actual,
                        between(written[key], start, end),
                        cost.rub_per_unit if cost else None,
                    )
                )
    return out


def detect(facts: Facts, all_rows: list[M1Row], norms: Norms) -> list[Draft]:
    by_period: dict[tuple[UUID, date, date], list[M1Row]] = defaultdict(list)
    history: dict[tuple[UUID, UUID], list[M1Row]] = defaultdict(list)
    for r in all_rows:
        by_period[(r.product, r.start, r.end)].append(r)
        history[(r.restaurant, r.product)].append(r)

    drafts: list[Draft] = []
    recipe_suspects: dict[
        UUID, tuple[date, date]
    ] = {}  # product -> latest period where the recipe looks wrong
    latest: dict[UUID, tuple[date, date]] = {}
    for product, start, end in by_period:
        if product not in latest or end > latest[product][1]:
            latest[product] = (start, end)
    for product, (start, end) in latest.items():
        group = by_period[(product, start, end)]
        info = facts.products[product]
        tol = norms.loss_allowance(info.category) / 100
        shares = [r.share for r in group]
        over = [r for r in group if r.share > tol]
        if (
            len(group) >= 2
            and Decimal(len(over)) / len(group) >= params.M1_NET_SHARE
            and med(shares) - tol >= params.M1_NET_EXCESS
        ):
            recipe_suspects[product] = (start, end)

    for product, (start, end) in recipe_suspects.items():
        group = by_period[(product, start, end)]
        info = facts.products[product]
        tol = norms.loss_allowance(info.category) / 100
        m = med([r.share for r in group])
        n_over = sum(1 for r in group if r.share > tol)
        drafts.append(
            Draft(
                key=f"M1:net:{info.code}",
                module="M1",
                kind="problem",
                process="accounting",
                restaurant=None,
                title=f"Техкарта, вероятно, устарела: {info.name}",
                headline=(
                    f"{n_over} из {len(group)} ресторанов расходуют больше техкарты, в среднем на {pct(m)} "
                    f"при допуске {pct(tol)} ({dmy(start + timedelta(days=1))}–{dmy(end)}). Одинаковое "
                    "отклонение по всей сети — признак ошибки в техкарте, а не в работе кухонь"
                ),
                effect_rub_month=None,
                effect_note="деньги не теряются, но фудкост и потери по сети считаются неверно",
                confidence="high" if len(group) >= 3 else "medium",
                period_from=start + timedelta(days=1),
                period_to=end,
                actions=list(ACTIONS_NETWORK),
                evidence={
                    "product": info.code,
                    "allowance": str(tol),
                    "median_share": str(m.quantize(Decimal("0.0001"))),
                    "restaurants": {
                        facts.restaurants[r.restaurant]: str(r.share.quantize(Decimal("0.0001")))
                        for r in group
                    },
                },
            )
        )

    for (restaurant, product), hist in history.items():
        hist.sort(key=lambda r: r.end)
        last = hist[-1]
        info = facts.products[product]
        tol = norms.loss_allowance(info.category) / 100
        group = by_period[(product, last.start, last.end)]
        network_median = med([r.share for r in group])
        use_network = len(group) >= params.NETWORK_Z_MIN_RESTAURANTS or product in recipe_suspects
        benchmark = max(tol, network_median) if use_network else tol
        if last.share <= benchmark:
            continue
        if len(group) >= params.NETWORK_Z_MIN_RESTAURANTS:
            z = robust_z(last.share, [r.share for r in group], params.M1_Z_FLOOR)
            if z <= params.M1_Z:
                continue
        else:
            z = None
        if last.unit_cost is None:
            effect = None
        else:
            effect = per_month(
                (last.share - benchmark) * last.theory * last.unit_cost, last.first_day, last.end
            )
            if effect < params.M1_MATERIALITY_RUB_MONTH:
                continue
        trend = [r.share for r in hist]
        growing = len(trend) >= 2 and all(b > a for a, b in pairwise(trend))
        drafts.append(
            Draft(
                key=f"M1:{facts.restaurants[restaurant]}:{info.code}",
                module="M1",
                kind="problem",
                process="production",
                restaurant=restaurant,
                title=f"Перерасход по техкарте: {info.name}",
                headline=(
                    f"За {dmy(last.first_day)}–{dmy(last.end)} расход на {pct(last.share)} больше техкарты "
                    f"при допуске {pct(tol)}"
                    + (f" и {pct(network_median)} в среднем по сети" if use_network else "")
                    + (f". Растет: {' → '.join(pct(s) for s in trend)}" if growing else "")
                    + (f". Потери ≈ {rub(effect)} в месяц" if effect is not None else "")
                ),
                effect_rub_month=effect,
                effect_note=None if effect is not None else "нет закупочных цен — сумму не оценить",
                confidence="high" if len(hist) >= 2 else "medium",
                period_from=last.first_day,
                period_to=last.end,
                actions=list(ACTIONS_RESTAURANT),
                evidence={
                    "product": info.code,
                    "allowance": str(tol),
                    "benchmark": str(benchmark.quantize(Decimal("0.0001"))),
                    "z": None if z is None else str(z.quantize(Decimal("0.01"))),
                    "periods": [
                        {
                            "from": r.first_day.isoformat(),
                            "to": r.end.isoformat(),
                            "theory": str(r.theory.quantize(Decimal("0.001"))),
                            "actual": str(r.actual.quantize(Decimal("0.001"))),
                            "write_off": str(r.write_off.quantize(Decimal("0.001"))),
                            "share": str(r.share.quantize(Decimal("0.0001"))),
                            "unit_cost": None
                            if r.unit_cost is None
                            else str(r.unit_cost.quantize(Decimal("0.01"))),
                        }
                        for r in hist
                    ],
                },
            )
        )
    return drafts
