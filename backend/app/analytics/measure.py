"""The measurement of a check: difference in differences, bootstrap interval (stage 7; docs/05, «Замер»).

A deterministic function of the uploaded rows — no person types a result and no model writes one:

- a **metric** per kind of finding (`Spec`), computed over a set of days as Σ numerator / Σ denominator
  (a share or a price), or per day (removals after the check was printed);
- the **effect** = (test after − test before) − (control after − control before), in the metric's units,
  then in ₽ a month with the test restaurant's own volumes and price before the check (an improvement is
  positive);
- the **interval**: 95 %, bootstrap by days — the days of each of the four cells drawn with replacement,
  1 000 times, the seed from the check, so the same measurement gives the same numbers;
- the **verdict**: confirmed (the whole interval above zero), inconclusive (the effect above zero, the
  interval reaching it), rejected (no effect above zero).

Designs (docs/05, «Эксперименты в пилоте на 3 ресторанах»): `restaurants` — the test restaurant against
similar ones; `items` — the product in the test restaurant against other products of its category there;
`before_after` — no control (weak evidence).
"""

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.analytics.facts import Facts
from app.analytics.usage import Usage

ZERO = Decimal(0)
REPS = 1000
MDE_FACTOR = Decimal("2.8")  # the effect a check sees with 80 % power at a 5 % level: 2.8 standard errors
KINDS = ("overuse", "writeoffs", "price", "discounts", "voids")
PER_DAY = ("voids",)  # a sum per day, not a share


@dataclass(frozen=True)
class Spec:
    """What is measured: the kind of metric and its object (from the finding)."""

    kind: str  # overuse | writeoffs | price | discounts | voids
    product: UUID | None = None  # overuse, writeoffs, price
    cashier: str | None = None  # discounts, voids: one cashier; None — the whole restaurant


@dataclass(frozen=True)
class Unit:
    """Whose rows: a restaurant, the products counted (None: the spec's own product) and, for a cashier's
    metric, whose sales: `whole` — the whole restaurant (another restaurant as the control), `others` — every
    cashier but the spec's (the same restaurant as the control). Code review of stage 7, p. 2."""

    restaurant: UUID
    products: frozenset[UUID] | None = None
    whole: bool = False
    others: bool = False

    def counts(self, spec: "Spec", cashier: str | None) -> bool:
        if spec.cashier is None or self.whole:
            return True
        return cashier != spec.cashier if self.others else cashier == spec.cashier


@dataclass
class Result:
    design: str
    before: tuple[date, date]
    after: tuple[date, date]
    days_after: int
    test_before: Decimal
    test_after: Decimal
    control_before: Decimal | None
    control_after: Decimal | None
    effect: Decimal  # in the metric's units; a share as a fraction (0.05 = 5 p.p.)
    effect_rub_month: Decimal  # an improvement is positive
    ci_low_rub_month: Decimal
    ci_high_rub_month: Decimal
    verdict: str  # confirmed | inconclusive | rejected
    weak: bool  # no control: before and after only
    rub_per_unit: Decimal  # how one unit of the metric's change converts to ₽ a month
    notes: list[str] = field(default_factory=list)


Daily = dict[date, tuple[Decimal, Decimal]]  # day -> (numerator, denominator)


def daily(facts: Facts, usage: Usage, spec: Spec, unit: Unit) -> Daily:
    """The metric's numerator and denominator by day, for one unit."""
    own = frozenset({spec.product} if spec.product else ())
    products = unit.products if unit.products is not None else own
    out: dict[date, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    if spec.kind == "overuse":
        for r in facts.receipts:
            if r.restaurant == unit.restaurant and r.product in products and r.qty > 0:
                out[r.day][0] += r.qty
        for p in products:
            for d, q in usage.by_day.get((unit.restaurant, p), {}).items():
                out[d][1] += q
    elif spec.kind == "writeoffs":
        # written off against the use by recipes: smooth by day, unlike the deliveries (review of stage 7)
        for w in facts.write_offs:
            if w.restaurant == unit.restaurant and w.product in products:
                out[w.day][0] += w.qty
        for p in products:
            for d, q in usage.by_day.get((unit.restaurant, p), {}).items():
                out[d][1] += q
    elif spec.kind == "price":
        for r in facts.receipts:
            if r.restaurant == unit.restaurant and r.product in products and r.qty > 0 and r.amount > 0:
                out[r.day][0] += r.amount
                out[r.day][1] += r.qty
    elif spec.kind == "discounts":
        for s in facts.sales:
            if s.restaurant == unit.restaurant and unit.counts(spec, s.cashier):
                out[s.day][0] += s.discount
                out[s.day][1] += s.revenue + s.discount
    elif spec.kind == "voids":
        days = {s.day for s in facts.sales if s.restaurant == unit.restaurant}
        for d in days:
            out[d][1] = Decimal(1)
        for v in facts.voids:
            if v.restaurant == unit.restaurant and v.after_print and unit.counts(spec, v.cashier):
                out[v.day][0] += v.amount
                out[v.day][1] = Decimal(1)
    else:
        raise ValueError(f"Unknown metric: {spec.kind}")
    return {d: (n, m) for d, (n, m) in out.items()}


def _pool(series: Iterable[Daily]) -> Daily:
    out: dict[date, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for s in series:
        for d, (n, m) in s.items():
            out[d][0] += n
            out[d][1] += m
    return {d: (n, m) for d, (n, m) in out.items()}


def _days(series: Daily, span: tuple[date, date]) -> list[tuple[Decimal, Decimal]]:
    start, end = span
    return [v for d, v in sorted(series.items()) if start <= d <= end]


def _value(rows: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    num = sum((n for n, _ in rows), ZERO)
    den = sum((m for _, m in rows), ZERO)
    return num / den if den > 0 else None


def active_days(facts: Facts, restaurant: UUID, span: tuple[date, date]) -> int:
    """The days the restaurant has sales in `span`: a month is 30 of them, not 30 calendar days of a short
    history (code review of stage 7, p. 5)."""
    days = {s.day for s in facts.sales if s.restaurant == restaurant and span[0] <= s.day <= span[1]}
    return len(days) or (span[1] - span[0]).days + 1


def _rub_per_unit(facts: Facts, usage: Usage, spec: Spec, test: Unit, before: tuple[date, date]) -> Decimal:
    """₽ a month one unit of the metric's change is worth, with the test's own volumes before the check."""
    rows = _days(daily(facts, usage, spec, test), before)
    per_month = Decimal(30) / active_days(facts, test.restaurant, before)
    if spec.kind in PER_DAY:
        return Decimal(30)
    if spec.kind == "price":
        return sum((m for _, m in rows), ZERO) * per_month  # quantity bought a month
    if spec.kind == "discounts":
        return sum((m for _, m in rows), ZERO) * per_month  # sales before discounts a month
    # overuse, writeoffs: the use by recipes a month, at the test's price before the check
    bought = [
        r
        for r in facts.receipts
        if r.restaurant == test.restaurant and r.product == spec.product and before[0] <= r.day <= before[1]
    ]
    qty = sum((r.qty for r in bought if r.qty > 0), ZERO)
    amount = sum((r.amount for r in bought if r.qty > 0), ZERO)
    price = amount / qty if qty > 0 else ZERO
    return sum((m for _, m in rows), ZERO) * per_month * price


def _did(cells: dict[str, list[tuple[Decimal, Decimal]]], has_control: bool) -> Decimal | None:
    tb, ta = _value(cells["tb"]), _value(cells["ta"])
    if tb is None or ta is None:
        return None
    if not has_control:
        return ta - tb
    cb, ca = _value(cells["cb"]), _value(cells["ca"])
    if cb is None or ca is None:
        return None
    return (ta - tb) - (ca - cb)


Cells = dict[str, list[tuple[Decimal, Decimal]]]  # tb, ta, cb, ca: test / control × before / after


MIN_SURVIVING = Decimal("0.95")  # draws with an empty denominator are dropped; fewer left — too little data


def _bootstrap(cells: Cells, has_control: bool, seed: int) -> list[Decimal]:
    rnd = random.Random(seed)  # noqa: S311  (resampling, not security)
    out = []
    for _ in range(REPS):
        drawn = {k: [rnd.choice(v) for _ in v] if v else [] for k, v in cells.items()}
        e = _did(drawn, has_control)
        if e is not None:
            out.append(e)
    return sorted(out)


def _percentile(values: list[Decimal], q: Decimal) -> Decimal:
    if not values:
        return ZERO
    i = int((q * (len(values) - 1)).to_integral_value(rounding=ROUND_HALF_UP))
    return values[i]


def _rub(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def measure(
    facts: Facts,
    usage: Usage,
    spec: Spec,
    design: str,
    test: Unit,
    controls: list[Unit],
    before: tuple[date, date],
    after: tuple[date, date],
    seed: int,
) -> Result | None:
    """The effect of a check over `after` against `before`; None when a cell has no data."""
    has_control = design != "before_after" and bool(controls)
    t = daily(facts, usage, spec, test)
    c = _pool(daily(facts, usage, spec, u) for u in controls) if has_control else {}
    cells = {"tb": _days(t, before), "ta": _days(t, after), "cb": _days(c, before), "ca": _days(c, after)}
    effect = _did(cells, has_control)
    if effect is None:
        return None
    rate = _rub_per_unit(facts, usage, spec, test, before)
    draws = _bootstrap(cells, has_control, seed)
    lo, hi = _percentile(draws, Decimal("0.025")), _percentile(draws, Decimal("0.975"))
    # lower is better for every metric: an improvement is a fall, worth ₽ above zero; the interval always
    # holds the point estimate, and the verdict is read from the interval as stored (code review 7, p. 11)
    rub = _rub(-effect * rate)
    rub_lo, rub_hi = _rub(min(-hi * rate, rub)), _rub(max(-lo * rate, rub))
    notes = []
    thin = len(draws) < MIN_SURVIVING * REPS
    if thin:
        notes.append("мало данных: в части повторов замера не нашлось ни одного дня с расходом")
    verdict = "confirmed" if rub_lo > 0 and not thin else "inconclusive" if rub > 0 else "rejected"
    return Result(
        design=design,
        before=before,
        after=after,
        days_after=(after[1] - after[0]).days + 1,  # calendar days of the check so far (p. 13)
        test_before=_value(cells["tb"]) or ZERO,
        test_after=_value(cells["ta"]) or ZERO,
        control_before=_value(cells["cb"]) if has_control else None,
        control_after=_value(cells["ca"]) if has_control else None,
        effect=effect,
        effect_rub_month=rub,
        ci_low_rub_month=rub_lo,
        ci_high_rub_month=rub_hi,
        verdict=verdict,
        weak=not has_control,
        rub_per_unit=rate,
        notes=notes,
    )


def mde_by_weeks(
    facts: Facts,
    usage: Usage,
    spec: Spec,
    design: str,
    test: Unit,
    controls: list[Unit],
    baseline: tuple[date, date],
    seed: int,
    weeks: Iterable[int],
) -> dict[int, Decimal] | None:
    """The smallest effect a check with this design would see, in ₽ a month, for each length: 2.8 standard
    errors of the effect. The error — the same bootstrap on the period before the check split in two (its
    halves stand for «before» and «after»); half of the variance comes from each part, and the «after» one
    shrinks as √(half / length) for a longer check (code review of stage 7, p. 7). None — no data."""
    start, end = baseline
    half = start + timedelta(days=(end - start).days // 2)
    has_control = design != "before_after" and bool(controls)
    t = daily(facts, usage, spec, test)
    c = _pool(daily(facts, usage, spec, u) for u in controls) if has_control else {}
    first, second = (start, half), (half + timedelta(days=1), end)
    cells = {"tb": _days(t, first), "ta": _days(t, second), "cb": _days(c, first), "ca": _days(c, second)}
    if has_control and not (cells["cb"] and cells["ca"]):
        return None
    draws = _bootstrap(cells, has_control, seed)
    if len(draws) < 2:
        return None
    mean = sum(draws, ZERO) / len(draws)
    sd = (sum(((d - mean) ** 2 for d in draws), ZERO) / (len(draws) - 1)).sqrt()
    rate = _rub_per_unit(facts, usage, spec, test, baseline)
    h = Decimal((second[1] - second[0]).days + 1)
    return {w: _rub(MDE_FACTOR * sd * ((1 + h / Decimal(7 * w)) / 2).sqrt() * rate) for w in weeks}


def mde_rub_month(
    facts: Facts,
    usage: Usage,
    spec: Spec,
    design: str,
    test: Unit,
    controls: list[Unit],
    baseline: tuple[date, date],
    seed: int,
    weeks: int = 4,
) -> Decimal | None:
    """`mde_by_weeks` for one length."""
    out = mde_by_weeks(facts, usage, spec, design, test, controls, baseline, seed, [weeks])
    return None if out is None else out[weeks]


def forecast_rub_month(
    facts: Facts,
    usage: Usage,
    spec: Spec,
    result: Result,
    others: list[UUID],
    window: tuple[date, date],
) -> Decimal:
    """What rolling a confirmed change out could give the rest of the network, ₽ a month: each other
    restaurant's room to improve over `window`, lowered by the share the measurement credits to the change
    (the effect net of the control, against the test's level before). The room is the metric itself, or for
    overuse what is bought above the recipes (level − 1). Not for a price (code review of stage 7, p. 4)."""
    if result.test_before <= 0 or result.effect >= 0 or spec.kind == "price":
        return ZERO
    base = result.test_before - 1 if spec.kind == "overuse" else result.test_before
    if base <= 0:
        return ZERO
    fall = min(-result.effect / base, Decimal(1))  # the change's own share of the improvement, 0…1
    total = ZERO
    for r in others:
        unit = Unit(r, whole=True)
        level = _value(_days(daily(facts, usage, spec, unit), window))
        if level is None:
            continue
        room = level - 1 if spec.kind == "overuse" else level
        if room <= 0:
            continue
        total += room * fall * _rub_per_unit(facts, usage, spec, unit, window)
    return _rub(total)
