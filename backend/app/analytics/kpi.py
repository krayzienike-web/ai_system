"""Restaurant KPIs for the overview screens (docs/12, «Показатели ресторана»).

- Actual food cost = cost of what was used between the last two stock counts (A × unit cost) / revenue of
  the days between them.
- Food cost by recipes = cost of what the recipes say for the dishes sold (T × unit cost) / the same revenue.
- Write-offs = cost of documented write-offs over the last `KPI_WRITE_OFF_DAYS` days of data / revenue of
  those days.
- The network: the same sums over all restaurants, i.e. the revenue-weighted average.
Products without a known cost add nothing to either side of a share.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.analytics.costs import CostBook
from app.analytics.facts import Facts
from app.analytics.m1 import M1Row

KPI_WRITE_OFF_DAYS = 28
ZERO = Decimal(0)


@dataclass(frozen=True)
class Kpi:
    restaurant: UUID | None  # None: the network
    food_cost_from: date | None
    food_cost_to: date | None
    revenue: Decimal  # of the food-cost period
    food_cost_actual: Decimal | None
    food_cost_theory: Decimal | None
    write_offs_from: date | None
    write_offs_to: date | None
    write_offs_share: Decimal | None


@dataclass
class _Sums:
    revenue: Decimal = ZERO
    actual: Decimal = ZERO
    theory: Decimal = ZERO
    wo_revenue: Decimal = ZERO
    write_offs: Decimal = ZERO


def _share(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part / whole).quantize(Decimal("0.000001")) if whole > 0 else None


def compute(facts: Facts, m1_rows: list[M1Row], costs: CostBook) -> list[Kpi]:
    """KPIs of every restaurant with data, then the network (last)."""
    # The last count period of each restaurant (the latest closing count).
    last: dict[UUID, tuple[date, date]] = {}
    for r in m1_rows:
        if r.restaurant not in last or r.end > last[r.restaurant][1]:
            last[r.restaurant] = (r.start, r.end)
    data_end = max((s.day for s in facts.sales), default=None)
    wo_start = data_end - timedelta(days=KPI_WRITE_OFF_DAYS - 1) if data_end else None

    sums: dict[UUID, _Sums] = defaultdict(_Sums)
    for r in m1_rows:
        if last.get(r.restaurant) == (r.start, r.end) and r.unit_cost is not None:
            sums[r.restaurant].actual += r.actual * r.unit_cost
            sums[r.restaurant].theory += r.theory * r.unit_cost
    for sale in facts.sales:
        period = last.get(sale.restaurant)
        if period and period[0] < sale.day <= period[1]:
            sums[sale.restaurant].revenue += sale.revenue
        if wo_start and data_end and wo_start <= sale.day <= data_end:
            sums[sale.restaurant].wo_revenue += sale.revenue
    if wo_start and data_end:
        for w in facts.write_offs:
            if wo_start <= w.day <= data_end:
                cost = costs.cost(w.restaurant, w.product, wo_start, data_end)
                if cost is not None:
                    sums[w.restaurant].write_offs += w.qty * cost.rub_per_unit

    out: list[Kpi] = []
    network = _Sums()
    for restaurant in sorted(set(sums) | set(last), key=lambda r: facts.restaurants.get(r, "")):
        s = sums[restaurant]
        period = last.get(restaurant)
        out.append(
            Kpi(
                restaurant,
                period[0] + timedelta(days=1) if period else None,
                period[1] if period else None,
                s.revenue,
                _share(s.actual, s.revenue),
                _share(s.theory, s.revenue),
                wo_start,
                data_end,
                _share(s.write_offs, s.wo_revenue),
            )
        )
        for name in ("revenue", "actual", "theory", "wo_revenue", "write_offs"):
            setattr(network, name, getattr(network, name) + getattr(s, name))
    periods = [p for p in last.values()]
    out.append(
        Kpi(
            None,
            min(p[0] for p in periods) + timedelta(days=1) if periods else None,
            max(p[1] for p in periods) if periods else None,
            network.revenue,
            _share(network.actual, network.revenue),
            _share(network.theory, network.revenue),
            wo_start,
            data_end,
            _share(network.write_offs, network.wo_revenue),
        )
    )
    return out
