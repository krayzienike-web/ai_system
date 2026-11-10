"""The measurement's rules one by one, on hand-made rows (stage 7, docs/05 «Замер»; after-review pass):
₽ a month per kind of metric, the length of «до», the verdict at its edges, «мало данных», the waiting for
late rows and a control restaurant left out after the grace period, the designs per kind, the forecast
(TC-EXP-21, 22, 24…27, 33, 34, 41…45, 49).

Every series is flat inside a period unless a test says otherwise: every bootstrap draw then equals the
point estimate, so the interval is the effect itself and every number can be worked out by hand. The
periods are 30 days and there are no sales unless a test adds them, so «a month» is the period itself
(30 / 30 days)."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.analytics import measure as m
from app.analytics.drafts import pct
from app.analytics.facts import Facts, ProductInfo, ReceiptRow, SaleRow, VoidRow, WriteOffRow
from app.analytics.measure import Result, Spec, Unit, forecast_rub_month, measure
from app.analytics.usage import Usage
from app.experiments import design
from app.experiments.measurement import _measure_one
from app.experiments.models import Experiment
from app.insights.models import Finding

D = Decimal
R1, R2, R3 = uuid4(), uuid4(), uuid4()
TOMATO, CUCUMBER = uuid4(), uuid4()
DISH = uuid4()
START = date(2026, 9, 14)
BEFORE = (START - timedelta(days=30), START - timedelta(days=1))
AFTER = (START, START + timedelta(days=29))


def _days(span: tuple[date, date]) -> list[date]:
    return [span[0] + timedelta(days=i) for i in range((span[1] - span[0]).days + 1)]


def _facts() -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.products = {
        TOMATO: ProductInfo("P06", "Томаты", "Овощи", "kg", 6, False),
        CUCUMBER: ProductInfo("P18", "Огурцы", "Овощи", "kg", 6, False),
    }
    return f


def _usage(f: Facts, per_day: dict[tuple[UUID, UUID], dict[date, Decimal]]) -> Usage:
    u = Usage(f)
    u.by_day.update(per_day)
    return u


def _flat(value: Decimal, span: tuple[date, date]) -> dict[date, Decimal]:
    return {d: value for d in _days(span)}


def _alone(f: Facts, usage: Usage, spec: Spec) -> Result:
    r = measure(f, usage, spec, "before_after", Unit(R1), [], BEFORE, AFTER, seed=7)
    assert r is not None
    return r


# ------------------------------------------------------------------ ₽ a month per kind (TC-EXP-21)


def _product_rows(
    f: Facts,
    bought: tuple[Decimal, Decimal],
    price: tuple[Decimal, Decimal],
    written: tuple[Decimal, Decimal],
) -> Usage:
    """R01's tomatoes: bought kg a day and ₽/kg, written off kg a day — (before, after); used by recipes
    10 kg a day all along."""
    for i, span in enumerate((BEFORE, AFTER)):
        for d in _days(span):
            f.receipts.append(ReceiptRow(R1, d, TOMATO, None, bought[i], bought[i] * price[i]))
            f.write_offs.append(WriteOffRow(R1, d, TOMATO, written[i], "spoiled"))
    return _usage(f, {(R1, TOMATO): _flat(D(10), (BEFORE[0], AFTER[1]))})


def test_overuse_is_worth_the_use_by_recipes_at_the_price_before_the_check() -> None:
    """M1: bought 12 → 11 kg a day against 10 used: 1.2 → 1.1, Δ = −0.1. ₽ a month = 0.1 × 300 kg used by
    recipes a month × 200 ₽/kg (the price *before*; after it the tomatoes cost 300 ₽) = 6 000 ₽. With the
    bought volume (360 kg) it would be 7 200, with the price after — 9 000."""
    f = _facts()
    usage = _product_rows(f, (D(12), D(11)), (D(200), D(300)), (D(0), D(0)))
    r = _alone(f, usage, Spec("overuse", TOMATO))
    assert (r.test_before, r.test_after, r.effect) == (D("1.2"), D("1.1"), D("-0.1"))
    assert r.rub_per_unit == D(60000)  # 300 kg × 200 ₽
    assert (r.effect_rub_month, r.ci_low_rub_month, r.ci_high_rub_month) == (D(6000), D(6000), D(6000))
    assert r.verdict == "confirmed" and r.weak


def test_writeoffs_are_worth_the_use_by_recipes_not_the_deliveries() -> None:
    """M5/M6: written off 1 → 0.5 kg a day of 10 used: 10% → 5%, Δ = −0.05. ₽ = 0.05 × 300 kg × 200 ₽ =
    3 000 ₽ (by the bought 360 kg it would be 3 600)."""
    f = _facts()
    usage = _product_rows(f, (D(12), D(12)), (D(200), D(200)), (D(1), D("0.5")))
    r = _alone(f, usage, Spec("writeoffs", TOMATO))
    assert (r.test_before, r.test_after, r.effect) == (D("0.1"), D("0.05"), D("-0.05"))
    assert r.effect_rub_month == D(3000) and r.verdict == "confirmed"


def test_a_price_is_worth_the_quantity_bought_a_month() -> None:
    """M3: 200 → 190 ₽/kg, Δ = −10 ₽; bought 10 kg a day = 300 kg a month → 10 × 300 = 3 000 ₽."""
    f = _facts()
    usage = _product_rows(f, (D(10), D(10)), (D(200), D(190)), (D(0), D(0)))
    r = _alone(f, usage, Spec("price", TOMATO))
    assert (r.test_before, r.test_after, r.effect) == (D(200), D(190), D(-10))
    assert r.rub_per_unit == D(300) and r.effect_rub_month == D(3000)


def _till(f: Facts, discount: tuple[Decimal, Decimal], voids: tuple[Decimal, Decimal]) -> None:
    """R01 sells 1 000 ₽ before discounts a day; discounts and voids after the check was printed —
    (before, after) a day; plus a void before printing (1 000 ₽) every day that never counts."""
    for i, span in enumerate((BEFORE, AFTER)):
        for d in _days(span):
            f.sales.append(SaleRow(R1, d, DISH, D(1), D(1000) - discount[i], discount[i], "таб. 104"))
            f.voids.append(VoidRow(R1, d, voids[i], "таб. 104", True))
            f.voids.append(VoidRow(R1, d, D(1000), "таб. 104", False))


def test_discounts_are_worth_the_sales_before_discounts_a_month() -> None:
    """M8 discounts: 100 → 50 ₽ of 1 000 a day: 10% → 5%, Δ = −0.05; sales before discounts in the 30 days
    with sales = 30 000 ₽ → 0.05 × 30 000 = 1 500 ₽."""
    f = _facts()
    _till(f, (D(100), D(50)), (D(0), D(0)))
    r = _alone(f, Usage(f), Spec("discounts"))
    assert (r.test_before, r.test_after, r.effect) == (D("0.1"), D("0.05"), D("-0.05"))
    assert r.rub_per_unit == D(30000) and r.effect_rub_month == D(1500)


def test_voids_are_worth_thirty_days_of_the_daily_sum() -> None:
    """M8 voids after the check was printed: 300 → 100 ₽ a day (the 1 000 ₽ voided before printing do not
    count), Δ = −200 ₽ a day → 200 × 30 = 6 000 ₽."""
    f = _facts()
    _till(f, (D(0), D(0)), (D(300), D(100)))
    r = _alone(f, Usage(f), Spec("voids", cashier="таб. 104"))
    assert (r.test_before, r.test_after, r.effect) == (D(300), D(100), D(-200))
    assert r.rub_per_unit == D(30) and r.effect_rub_month == D(6000)


def test_a_rise_is_a_loss_and_is_not_confirmed() -> None:
    """Lower is better: written off 5% → 10%, Δ = +0.05 → −0.05 × 60 000 = −3 000 ₽, «не подтвержден»."""
    f = _facts()
    usage = _product_rows(f, (D(12), D(12)), (D(200), D(200)), (D("0.5"), D(1)))
    r = _alone(f, usage, Spec("writeoffs", TOMATO))
    assert r.effect == D("0.05") and r.effect_rub_month == D(-3000) and r.verdict == "rejected"


# ------------------------------------------------------------------ the verdict at its edges (TC-EXP-24)


def test_an_effect_that_rounds_to_zero_rubles_is_not_confirmed() -> None:
    """Tomatoes at 1 ₽/kg: 10% → 9.9% of 300 kg is 0.001 × 300 = 0.3 ₽ a month → 0 ₽, not above zero."""
    f = _facts()
    usage = _product_rows(f, (D(12), D(12)), (D(1), D(1)), (D(1), D("0.99")))
    r = _alone(f, usage, Spec("writeoffs", TOMATO))
    assert r.effect == D("-0.001") and r.rub_per_unit == D(300)
    assert (r.effect_rub_month, r.ci_low_rub_month, r.ci_high_rub_month) == (D(0), D(0), D(0))
    assert r.verdict == "rejected"


@pytest.mark.parametrize(
    ("top", "low", "verdict"),
    [
        (D(0), D(0), "inconclusive"),  # the interval's lower bound is exactly 0 ₽: it reaches zero
        (D("-0.00001"), D(1), "confirmed"),  # 0.00001 × 60 000 = 0.6 → 1 ₽: the whole interval is above zero
    ],
)
def test_a_lower_bound_of_exactly_zero_is_not_significant(
    monkeypatch: pytest.MonkeyPatch, top: Decimal, low: Decimal, verdict: str
) -> None:
    """10% → 9%: Δ = −0.01, × 60 000 = 600 ₽. The draws are set by hand: 974 at −0.01 and 26 at `top`;
    the 97.5th percentile is draw round(0.975 × 999) = 974 (0-based) → `top`, so the lower bound in ₽ is
    −top × 60 000: 0 ₽ — «не значимо», 0.6 → 1 ₽ — «подтвержден»."""
    f = _facts()
    usage = _product_rows(f, (D(12), D(12)), (D(200), D(200)), (D(1), D("0.9")))
    monkeypatch.setattr(m, "_bootstrap", lambda *_: [D("-0.01")] * 974 + [top] * 26)
    r = _alone(f, usage, Spec("writeoffs", TOMATO))
    assert r.effect_rub_month == D(600) and r.ci_low_rub_month == low and r.ci_high_rub_month == D(600)
    assert r.verdict == verdict


def test_too_few_surviving_draws_say_too_little_data_and_never_confirm() -> None:
    """After the start the tomatoes were used on one day of 30 (10 kg, 0.5 written off), the other 29 days
    have write-off rows of 0 and no use. A draw of 30 days misses the one day with a chance of
    (29/30)^30 ≈ 36%, so only ≈ 64% of the draws survive (< 95%): «мало данных». Every surviving draw is
    0.5 / 10 = 5% → Δ = −0.05 → 3 000 ₽ — the interval is 3 000…3 000, yet the verdict stays «не значимо»."""
    f = _facts()
    for d in _days(BEFORE):
        f.receipts.append(ReceiptRow(R1, d, TOMATO, None, D(12), D(2400)))
        f.write_offs.append(WriteOffRow(R1, d, TOMATO, D(1), "spoiled"))
    for i, d in enumerate(_days(AFTER)):
        f.write_offs.append(WriteOffRow(R1, d, TOMATO, D("0.5") if i == 0 else D(0), "spoiled"))
    usage = _usage(f, {(R1, TOMATO): {**_flat(D(10), BEFORE), AFTER[0]: D(10)}})
    r = _alone(f, usage, Spec("writeoffs", TOMATO))
    assert r.effect == D("-0.05") and r.effect_rub_month == D(3000) and r.ci_low_rub_month == D(3000)
    assert r.verdict == "inconclusive"
    assert r.notes == ["мало данных: в части повторов замера не нашлось ни одного дня с расходом"]


# ------------------------------------------------------------------ periods (TC-EXP-22)


@pytest.mark.parametrize(
    ("weeks", "days"),
    [(2, 28), (4, 28), (6, 42), (8, 56)],  # not shorter than 4 weeks; a repeat of 8 weeks — 8 weeks before
)
def test_the_period_before_is_as_long_as_the_check_but_not_shorter_than_four_weeks(
    weeks: int, days: int
) -> None:
    starts = date(2026, 10, 26)
    first, last = design.baseline(starts, starts + timedelta(weeks=weeks))
    assert last == date(2026, 10, 25)  # it ends the day before the start
    assert (last - first).days + 1 == days


# ------------------------------------------------------------------ what a finding measures (TC-EXP-34)


def _finding(module: str, **evidence: object) -> Finding:
    return Finding(module=module, restaurant_id=R1, key=evidence.pop("key", None), evidence=evidence)


def test_the_metric_follows_the_kind_of_finding() -> None:
    """docs/05, table «Метрика»: M1 — overuse (not «under»), M5 and M6 overstock — write-offs, M3 — the
    price, M8 — the cashier's discounts or voids; the rest and a network finding — no metric (a task)."""
    codes = {"P06": TOMATO}
    assert design.spec_for(_finding("M1", product="P06"), codes) == Spec("overuse", TOMATO)
    assert design.spec_for(_finding("M1", product="P06", key="M1:R01:P06:under"), codes) is None
    assert design.spec_for(_finding("M5", product="P06"), codes) == Spec("writeoffs", TOMATO)
    assert design.spec_for(_finding("M6", product="P06", kind="overstock"), codes) == Spec(
        "writeoffs", TOMATO
    )
    assert design.spec_for(_finding("M6", product="P06", kind="shortage"), codes) is None
    assert design.spec_for(_finding("M3", product="P06"), codes) == Spec("price", TOMATO)
    assert design.spec_for(_finding("M8", kind="voids", cashier="таб. 104"), codes) == Spec(
        "voids", cashier="таб. 104"
    )
    assert design.spec_for(_finding("M4", product="P06"), codes) is None
    network = _finding("M5", product="P06")
    network.restaurant_id = None
    assert design.spec_for(network, codes) is None


# ------------------------------------------------------------------ designs per kind (TC-EXP-33, 42…44)


def _shop() -> tuple[Facts, Usage]:
    """R01 uses tomatoes and cucumbers (one category), R02 — tomatoes; 60 days of slightly uneven rows."""
    f = _facts()
    span = (BEFORE[0], AFTER[1])
    for i, d in enumerate(_days(span)):
        for r in (R1, R2):
            for p in (TOMATO, CUCUMBER):
                f.receipts.append(ReceiptRow(r, d, p, None, D(10), D(2000 + 10 * (i % 3))))
                f.write_offs.append(WriteOffRow(r, d, p, D(1) + D(i % 2) / 10, "spoiled"))
            f.sales.append(
                SaleRow(r, d, DISH, D(1), D(900 + i % 5), D(100), "таб. 104" if r == R1 else "таб. 201")
            )
            f.sales.append(SaleRow(r, d, DISH, D(1), D(950), D(50), "таб. 101"))
    usage = _usage(f, {(r, p): _flat(D(10), span) for r in (R1, R2) for p in (TOMATO, CUCUMBER)})
    return f, usage


def _options(spec: Spec) -> dict[str, design.Option]:
    f, usage = _shop()
    opts = design.options(
        f, spec, R1, [R2], AFTER[1] + timedelta(days=1), AFTER[1] + timedelta(weeks=4), 7, usage
    )
    return {o.design: o for o in opts}


def test_items_are_offered_for_a_share_of_a_product_but_never_for_a_price() -> None:
    """docs/05: «Для цены (M3) дизайн 2 не предлагается: цены разных товаров между собой не сравнить» — even
    though cucumbers of the same category are there; for write-offs they are the control."""
    price = _options(Spec("price", TOMATO))
    assert not price["items"].available and price["items"].note == "для цены не подходит"
    assert price["items"].control_products == [] and price["items"].mde_by_weeks == {}
    shares = _options(Spec("writeoffs", TOMATO))
    assert shares["items"].available and shares["items"].control_products == [CUCUMBER]
    assert "огурцы" in shares["items"].note
    for o in (price, shares):
        assert o["restaurants"].available and o["before_after"].available and o["before_after"].weak


def test_a_cashier_is_compared_with_the_other_cashiers_or_whole_restaurants() -> None:
    """docs/05: for a cashier (M8) the control is the comparison restaurants as a whole or the other
    cashiers of the same restaurant; a discount finding of the whole restaurant has no «items»."""
    spec = Spec("discounts", cashier="таб. 104")
    me, others = design.units(spec, "items", R1, [R2], [])
    assert me == Unit(R1) and others == [Unit(R1, others=True)]
    assert design.units(spec, "restaurants", R1, [R2, R3], [])[1] == [
        Unit(R2, whole=True),
        Unit(R3, whole=True),
    ]
    assert design.units(spec, "before_after", R1, [R2], [])[1] == []
    by = _options(spec)
    assert by["items"].available and by["items"].note == "сравниваем с другими кассирами этого ресторана"
    assert by["restaurants"].note.endswith("(весь ресторан)")
    whole = _options(Spec("discounts"))
    assert not whole["items"].available


def test_the_smallest_visible_effect_is_given_for_each_length_and_falls_with_it() -> None:
    """docs/05: the draft shows the threshold per design and per 2, 4, 6 weeks; longer — smaller."""
    by = _options(Spec("writeoffs", TOMATO))
    for key in ("restaurants", "items", "before_after"):
        mde = by[key].mde_by_weeks
        assert sorted(mde) == [2, 4, 6] and mde[2] > mde[4] > mde[6] > 0, key


def _opt(key: str, mde: int | None, available: bool = True) -> design.Option:
    return design.Option(
        key, key, available, "", key == "before_after", {} if mde is None else {4: D(mde)}, []
    )


def test_the_recommended_design_is_the_one_that_would_see_the_expected_effect() -> None:
    """Restaurants see 5 000 ₽, items 2 000, before-and-after 100 (weak, never recommended while another
    fits). Expected 6 000 — restaurants (fewest assumptions first); 3 000 — only items see it; 1 000 — none
    sees it: the one with the smallest threshold (the wizard warns, TC-EXP-33); none fits — before/after."""
    opts = [_opt("restaurants", 5000), _opt("items", 2000), _opt("before_after", 100)]
    assert design.recommended(opts, D(6000), 4) == "restaurants"
    assert design.recommended(opts, D(3000), 4) == "items"
    assert design.recommended(opts, D(1000), 4) == "items"
    assert design.recommended(
        [_opt("restaurants", 1, False), _opt("items", None), _opt("before_after", 1)], D(10), 4
    ) == ("before_after")


# ------------------------------------------------------------------ the forecast (TC-EXP-45)


def _result(kind_before: Decimal, effect: Decimal) -> Result:
    return Result(
        "restaurants",
        BEFORE,
        AFTER,
        30,
        kind_before,
        kind_before + effect,
        None,
        None,
        effect,
        D(1000),
        D(500),
        D(1500),
        "confirmed",
        False,
        D(1),
    )


def test_no_forecast_for_a_price_a_rise_or_no_level_before() -> None:
    """docs/05: «Для цены не считается»; nothing to roll out from a rise or from a zero level before."""
    f, usage = _shop()
    window = AFTER
    assert forecast_rub_month(f, usage, Spec("price", TOMATO), _result(D(200), D(-10)), [R2], window) == 0
    assert (
        forecast_rub_month(f, usage, Spec("writeoffs", TOMATO), _result(D("0.1"), D("0.02")), [R2], window)
        == 0
    )
    assert (
        forecast_rub_month(f, usage, Spec("writeoffs", TOMATO), _result(D(0), D("-0.01")), [R2], window) == 0
    )
    # the same fall of write-offs does forecast for R02 (its own write-offs ≈ 10.5% of its use)
    assert (
        forecast_rub_month(f, usage, Spec("writeoffs", TOMATO), _result(D("0.1"), D("-0.05")), [R2], window)
        > 0
    )


# ------------------------------------------------ waiting, the grace period, closing (TC-EXP-26, 27, 41, 49)


class _NoTasks:
    """Stands for the session: the check has no tasks, nothing to flush."""

    def execute(self, _query: object) -> SimpleNamespace:
        return SimpleNamespace(scalars=lambda: [])

    def flush(self) -> None:
        pass


ENDS = START + timedelta(days=27)  # 11.10: a 4-week check (28 days, 14.09…11.10)
CHECK = uuid4()  # one check: its id is the bootstrap's seed


def _check() -> Experiment:
    first, last = design.baseline(START, ENDS)
    return Experiment(
        id=CHECK,
        tenant_id=uuid4(),
        title="Малые партии томатов",
        hypothesis="—",
        metric="—",
        test_restaurant_ids=[R1],
        control_restaurant_ids=[R2, R3],
        control_product_ids=[],
        starts_on=START,
        ends_on=ENDS,
        expected_rub_month=D(1000),
        status="running",
        design="restaurants",
        metric_kind="writeoffs",
        metric_product_id=TOMATO,
        baseline_from=first,
        baseline_to=last,
    )


def _uploaded(last: dict[UUID, date]) -> tuple[Facts, Usage]:
    """Tomatoes written off: R01 10% → 5%, R02 3%, R03 6% all along; each restaurant's sales, receipts and
    write-offs up to its `last` day."""
    f = _facts()
    share = {R1: (D("0.1"), D("0.05")), R2: (D("0.03"), D("0.03")), R3: (D("0.06"), D("0.06"))}
    per_day: dict[tuple[UUID, UUID], dict[date, Decimal]] = {}
    for r, until in last.items():
        days = _days((START - timedelta(days=28), until))
        per_day[(r, TOMATO)] = {d: D(10) for d in days}
        for d in days:
            f.sales.append(SaleRow(r, d, DISH, D(1), D(1000)))
            f.receipts.append(ReceiptRow(r, d, TOMATO, None, D(10), D(2000)))
            f.write_offs.append(WriteOffRow(r, d, TOMATO, D(10) * share[r][d >= START], "spoiled"))
    return f, _usage(f, per_day)


def _measure(last: dict[UUID, date], today: date) -> Experiment:
    exp = _check()
    f, usage = _uploaded(last)
    _measure_one(_NoTasks(), exp, f, usage, today)  # type: ignore[arg-type]
    return exp


def test_a_control_restaurant_without_its_rows_is_waited_for_then_left_out() -> None:
    """docs/05 «Ход и итог»: R03 uploaded only up to 01.10 (10 days before the end, 11.10). Until 14 days
    after the end (25.10 inclusive) the check waits for its rows; on 26.10 R03 is left out with a note and the
    result is R01 against R02 alone: 10% → 5% against 3% → 3% — Δ = −5 п.п.; ₽ = 0.05 × 300 kg used a month
    (28 days of sales before → 280 × 30 / 28) × 200 ₽ = 3 000 ₽."""
    last = {R1: ENDS, R2: ENDS, R3: ENDS - timedelta(days=10)}
    for today in (ENDS + timedelta(days=1), ENDS + timedelta(days=14)):
        waiting = _measure(last, today)
        assert waiting.status == "running" and waiting.verdict is None, today
        assert waiting.progress_text == "Срок прошел; ждем данных по 11.10, чтобы подвести итог."
    done = _measure(last, ENDS + timedelta(days=15))
    assert done.status == "completed" and done.verdict == "confirmed"
    assert done.effect_rub_month == D(3000) and done.completed_on == ENDS + timedelta(days=15)
    assert f"рестораны сравнения: {pct(D('0.03'))} → {pct(D('0.03'))}" in (done.result_text or "")
    assert (done.result_text or "").endswith(". Без R03 — их данных за период нет")


def test_every_control_late_waits_through_the_grace_period() -> None:
    """Every control 3 days short of the end: within the 14 days after it the check waits."""
    exp = _measure(
        {R1: ENDS, R2: ENDS - timedelta(days=3), R3: ENDS - timedelta(days=3)}, ENDS + timedelta(days=14)
    )
    assert (
        exp.status == "running"
        and exp.progress_text == "Срок прошел; ждем данных по 11.10, чтобы подвести итог."
    )


def test_every_control_late_after_the_grace_period_closes_the_check() -> None:
    """R02 and R03 stopped 3 days before the end; 30 days after it neither has come: both are left out, there
    is nothing to compare with — the check is closed as «не значимо», not left «ждем данных» for ever."""
    exp = _measure(
        {R1: ENDS, R2: ENDS - timedelta(days=3), R3: ENDS - timedelta(days=3)}, ENDS + timedelta(days=30)
    )
    assert exp.status == "completed" and exp.verdict == "inconclusive"
    assert (exp.result_text or "").startswith("Сравнить не с чем: рестораны сравнения")


def test_the_test_restaurant_late_is_never_left_out() -> None:
    """The grace period is for the control only: without the test restaurant's rows there is no result."""
    exp = _measure({R1: ENDS - timedelta(days=3), R2: ENDS, R3: ENDS}, ENDS + timedelta(days=30))
    assert exp.status == "running" and exp.verdict is None


def test_measuring_the_same_rows_twice_writes_the_same_words() -> None:
    """Principle 4: an interim measurement on 01.10 (18 days: 14.09…01.10) repeated on the same rows — the
    same text to the letter; the final one — the same numbers."""
    last = {R1: date(2026, 10, 1), R2: date(2026, 10, 1), R3: date(2026, 10, 1)}
    a, b = _measure(last, date(2026, 10, 2)), _measure(last, date(2026, 10, 2))
    assert a.status == b.status == "running" and a.progress_text == b.progress_text
    assert (a.progress_text or "").startswith("За 18 дн. проверки:")
    full = {R1: ENDS, R2: ENDS, R3: ENDS}
    x, y = _measure(full, ENDS + timedelta(days=1)), _measure(full, ENDS + timedelta(days=1))
    assert (x.verdict, x.effect_rub_month, x.ci_low_rub_month, x.ci_high_rub_month, x.result_text) == (
        y.verdict,
        y.effect_rub_month,
        y.ci_low_rub_month,
        y.ci_high_rub_month,
        y.result_text,
    )


def test_the_verdict_does_not_depend_on_the_expected_effect() -> None:
    """docs/05 «Честность замера»: no fitting — expecting 1 ₽ or 1 000 000 ₽ gives the same result."""
    full = {R1: ENDS, R2: ENDS, R3: ENDS}
    small, big = _check(), _check()
    small.expected_rub_month, big.expected_rub_month = D(1), D(1000000)
    for exp in (small, big):
        f, usage = _uploaded(full)
        _measure_one(_NoTasks(), exp, f, usage, ENDS + timedelta(days=1))  # type: ignore[arg-type]
    assert small.verdict == big.verdict == "confirmed"
    assert (small.effect_rub_month, small.result_text) == (big.effect_rub_month, big.result_text)


def test_no_rows_after_the_start_waits_and_nothing_to_compare_at_the_end_closes() -> None:
    """docs/05 «Ход и итог»: before any row after the start — «данных пока нет», no verdict; at the end the
    restaurants uploaded everything, but the tomatoes were never used after the start (no denominator):
    the check is closed as «не значимо» with 0 ₽ and the reason, not left running."""
    exp = _check()
    f, usage = _uploaded({R1: START - timedelta(days=1), R2: ENDS, R3: ENDS})
    _measure_one(_NoTasks(), exp, f, usage, START + timedelta(days=5))  # type: ignore[arg-type]
    assert exp.status == "running" and exp.progress_text == (
        "Данных после начала проверки пока нет — замер после загрузки продаж и закупок."
    )
    exp = _check()
    f, usage = _uploaded({R1: ENDS, R2: ENDS, R3: ENDS})
    usage.by_day[(R1, TOMATO)] = {d: q for d, q in usage.by_day[(R1, TOMATO)].items() if d < START}
    _measure_one(_NoTasks(), exp, f, usage, ENDS + timedelta(days=1))  # type: ignore[arg-type]
    assert exp.status == "completed" and exp.verdict == "inconclusive" and exp.progress_text is None
    assert (exp.effect_rub_month, exp.ci_low_rub_month, exp.ci_high_rub_month) == (D(0), D(0), D(0))
    assert exp.result_text == "Замерить нечего: за период проверки или до нее нет строк по этому показателю"


def test_one_broken_check_does_not_stop_the_others() -> None:
    """A check whose metric cannot be computed says so; the next check of the network is still measured."""
    from app.experiments.measurement import measure_all

    broken, fine = _check(), _check()
    broken.id, broken.metric_kind = uuid4(), "bogus"
    calls = iter([[broken, fine]])

    class _Session(_NoTasks):
        def execute(self, _query: object) -> SimpleNamespace:
            rows = next(calls, [])
            return SimpleNamespace(scalars=lambda: rows)

    f, usage = _uploaded({R1: ENDS, R2: ENDS, R3: ENDS})
    done = measure_all(_Session(), SimpleNamespace(tenant_id=uuid4()), f, ENDS + timedelta(days=1), usage)  # type: ignore[arg-type]
    assert done == 1 and fine.status == "completed" and broken.status == "running"
    assert broken.progress_text == "Замер не удался — проверьте товар и рестораны проверки."
