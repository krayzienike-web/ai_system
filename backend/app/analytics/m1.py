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

from app.analytics.costs import CostBook
from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts, ProductInfo
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.stats import med, robust_z
from app.analytics.usage import Usage
from app.norms.service import Norms

ACTIONS_RESTAURANT = [
    "Проверить вес порций на раздаче: контрольное взвешивание 10 блюд",
    "Сверить выход при обработке с техкартой",
    "Проверить, все ли списания оформлены",
]
ACTIONS_UNDER = [
    "Проверить вес порций на раздаче: не кладут ли меньше техкарты",
    "Сверить приходы и перемещения: весь ли товар проведен накладными",
    "Проверить, не заменяют ли товар другим (пересорт)",
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


def _network_share(group: list[M1Row]) -> str | None:
    return str(med([r.share for r in group]).quantize(Decimal("0.0001"))) if len(group) >= 2 else None


class Peers:
    """The network to compare a period with. Restaurants count stock on their own days (Q15): each restaurant
    takes part with its period that ended closest to this one, within `M1_NET_ALIGN_DAYS`. Shares are rates,
    so periods of slightly different length are comparable."""

    def __init__(self, all_rows: list[M1Row], align_days: int) -> None:
        self.align = timedelta(days=align_days)
        self.by_product: dict[UUID, dict[UUID, list[M1Row]]] = defaultdict(lambda: defaultdict(list))
        for r in all_rows:
            self.by_product[r.product][r.restaurant].append(r)

    def around(self, product: UUID, end: date) -> list[M1Row]:
        group = []
        for periods in self.by_product.get(product, {}).values():
            near = [r for r in periods if abs(r.end - end) <= self.align]
            if near:
                group.append(min(near, key=lambda r: (abs(r.end - end), -r.end.toordinal())))
        return group

    def latest_end(self, product: UUID) -> date:
        return max(r.end for periods in self.by_product[product].values() for r in periods)


def rows(facts: Facts, usage: Usage, costs: CostBook, cfg: EngineParams = DEFAULT) -> list[M1Row]:
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
            if (end - start).days < cfg.M1_MIN_THEORY_DAYS:
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


def detect(facts: Facts, all_rows: list[M1Row], norms: Norms, cfg: EngineParams = DEFAULT) -> list[Draft]:
    history: dict[tuple[UUID, UUID], list[M1Row]] = defaultdict(list)
    for r in all_rows:
        history[(r.restaurant, r.product)].append(r)

    drafts: list[Draft] = []
    peers = Peers(all_rows, cfg.M1_NET_ALIGN_DAYS)
    # product -> the network's latest periods, where the recipe looks wrong
    recipe_suspects: dict[UUID, list[M1Row]] = {}
    for product in peers.by_product:
        group = peers.around(product, peers.latest_end(product))
        info = facts.products[product]
        tol = norms.loss_allowance(info.category) / 100
        shares = [r.share for r in group]
        over = [r for r in group if r.share > tol]
        if (
            len(group) >= 2
            and Decimal(len(over)) / len(group) >= cfg.M1_NET_SHARE
            and med(shares) - tol >= cfg.M1_NET_EXCESS
        ):
            recipe_suspects[product] = group

    for product, group in recipe_suspects.items():
        start, end = min(r.start for r in group), max(r.end for r in group)
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
                    # Each restaurant's own period (own counting days): the check recomputes it.
                    "periods": {
                        facts.restaurants[r.restaurant]: [r.first_day.isoformat(), r.end.isoformat()]
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
        group = peers.around(product, last.end)
        network_median = med([r.share for r in group])
        use_network = len(group) >= cfg.NETWORK_Z_MIN_RESTAURANTS or product in recipe_suspects
        benchmark = max(tol, network_median) if use_network else tol
        if last.share < -cfg.M1_UNDER:
            under = _under(facts, restaurant, info, hist, peers, cfg)
            if under is not None:
                drafts.append(under)
            continue
        if last.share <= benchmark:
            continue
        if len(group) >= cfg.NETWORK_Z_MIN_RESTAURANTS:
            z = robust_z(last.share, [r.share for r in group], cfg.M1_Z_FLOOR)
            if z <= cfg.M1_Z:
                continue
        else:
            z = None
        if last.unit_cost is None:
            effect = None
        else:
            effect = per_month(
                (last.share - benchmark) * last.theory * last.unit_cost, last.first_day, last.end
            )
            if effect < cfg.M1_MATERIALITY_RUB_MONTH:
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
                    "periods": _periods(hist, peers),
                },
            )
        )
    return drafts


def _periods(hist: list[M1Row], peers: Peers) -> list[dict[str, str | None]]:
    return [
        {
            "from": r.first_day.isoformat(),
            "to": r.end.isoformat(),
            "theory": str(r.theory.quantize(Decimal("0.001"))),
            "actual": str(r.actual.quantize(Decimal("0.001"))),
            "write_off": str(r.write_off.quantize(Decimal("0.001"))),
            "share": str(r.share.quantize(Decimal("0.0001"))),
            # The network's median around this period (2+ restaurants with a period ending close to it).
            "network_share": _network_share(peers.around(r.product, r.end)),
            "unit_cost": None if r.unit_cost is None else str(r.unit_cost.quantize(Decimal("0.01"))),
        }
        for r in hist
    ]


def _under(
    facts: Facts,
    restaurant: UUID,
    info: ProductInfo,
    hist: list[M1Row],
    peers: Peers,
    cfg: EngineParams,
) -> Draft | None:
    """Used less than the recipes say (E3): guests may get less than the recipe, or receipts are not recorded.
    Not money lost, so no effect in rubles; the shortfall's value decides whether it is worth attention."""
    last = hist[-1]
    group = peers.around(last.product, last.end)
    network_median = med([r.share for r in group])
    z = None
    if len(group) >= cfg.NETWORK_Z_MIN_RESTAURANTS:
        z = robust_z(last.share, [r.share for r in group], cfg.M1_Z_FLOOR)
        if z >= -cfg.M1_Z:
            return None
    shortfall = None
    if last.unit_cost is not None:
        shortfall = per_month(-last.unexplained * last.unit_cost, last.first_day, last.end)
        if shortfall < cfg.M1_MATERIALITY_RUB_MONTH:
            return None
    code, name = info.code, info.name
    unders = sum(1 for r in hist if r.share < -cfg.M1_UNDER)
    return Draft(
        key=f"M1:{facts.restaurants[restaurant]}:{code}:under",
        module="M1",
        kind="problem",
        process="production",
        restaurant=restaurant,
        title=f"Расход меньше техкарты: {name}",
        headline=(
            f"За {dmy(last.first_day)}–{dmy(last.end)} израсходовано на {pct(-last.share)} меньше, чем по "
            "техкартам проданных блюд"
            + (f", в среднем по сети {pct(network_median)}" if len(group) >= 2 else "")
            + (f". Это товар на ≈ {rub(shortfall)} в месяц" if shortfall is not None else "")
            + ". Гости могут получать меньше положенного, или часть прихода не проведена"
        ),
        effect_rub_month=None,
        effect_note="денег не теряет, но это риск качества блюд или неучтенный приход",
        confidence="high" if unders >= 2 else "medium",
        period_from=last.first_day,
        period_to=last.end,
        actions=list(ACTIONS_UNDER),
        evidence={
            "product": code,
            "direction": "under",
            "under": str(cfg.M1_UNDER),
            "shortfall_rub_month": None if shortfall is None else str(shortfall.quantize(Decimal("0.01"))),
            "z": None if z is None else str(z.quantize(Decimal("0.01"))),
            "periods": _periods(hist, peers),
        },
    )
