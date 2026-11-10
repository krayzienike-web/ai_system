"""The measurement of a check: difference in differences, bootstrap interval, honest verdict (stage 7,
docs/05 «Замер»; TC-EXP-20, 23, 24, 29–31, 33)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.analytics.facts import Facts, ProductInfo, ReceiptRow, WriteOffRow
from app.analytics.measure import Spec, Unit, mde_rub_month, measure
from app.analytics.usage import Usage

D = Decimal
R1, R2, R3 = uuid4(), uuid4(), uuid4()
TOMATO, CUCUMBER = uuid4(), uuid4()
START = date(2026, 9, 14)
BEFORE = (START - timedelta(days=28), START - timedelta(days=1))
AFTER = (START, START + timedelta(days=27))


Shares = dict[tuple[UUID, UUID], Decimal]


def _facts(share_before: Shares, share_after: Shares, wobble: int = 0) -> Facts:
    """10 kg a day bought at 200 ₽/kg; written off: the restaurant's share (before / after the start)."""
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.products = {
        TOMATO: ProductInfo("P06", "Томаты", "Овощи", "kg", 6, False),
        CUCUMBER: ProductInfo("P18", "Огурцы", "Овощи", "kg", 6, False),
    }
    for i in range(56):
        day = BEFORE[0] + timedelta(days=i)
        for r in (R1, R2, R3):
            for p in (TOMATO, CUCUMBER):
                f.receipts.append(ReceiptRow(r, day, p, None, D(10), D(2000)))
                share = (share_before if day < START else share_after).get((r, p), D("0.03"))
                noise = D(wobble) / 100 * (1 if i % 2 else -1)  # day-to-day ups and downs
                f.write_offs.append(WriteOffRow(r, day, p, D(10) * max(share + noise, D(0)), "spoiled"))
    return f


def _usage(f: Facts) -> Usage:
    """Used by recipes: 10 kg a day of each product in each restaurant, every day with receipts."""
    u = Usage(f)
    for r in (R1, R2, R3):
        for p in (TOMATO, CUCUMBER):
            u.by_day[(r, p)] = {x.day: D(10) for x in f.receipts if x.restaurant == r and x.product == p}
    return u


def _run(f: Facts, design: str = "restaurants", controls: list[Unit] | None = None):  # type: ignore[no-untyped-def]
    controls = [Unit(R2), Unit(R3)] if controls is None else controls
    return measure(f, _usage(f), Spec("writeoffs", TOMATO), design, Unit(R1), controls, BEFORE, AFTER, seed=7)


def test_a_clear_fall_against_steady_controls_is_confirmed_with_its_rubles() -> None:
    res = _run(_facts({(R1, TOMATO): D("0.10")}, {(R1, TOMATO): D("0.05")}, wobble=1))
    assert res is not None and res.verdict == "confirmed" and not res.weak
    assert res.test_before == D("0.10") and res.test_after == D("0.05") and res.effect == D("-0.05")
    # 5 p.p. of 300 kg used a month at 200 ₽/kg → 3 000 ₽ a month
    assert res.effect_rub_month == D(3000) and res.ci_low_rub_month > 0
    assert res.ci_low_rub_month <= res.effect_rub_month <= res.ci_high_rub_month


def test_the_same_check_measured_again_gives_the_same_numbers() -> None:
    f = _facts({(R1, TOMATO): D("0.10")}, {(R1, TOMATO): D("0.06")}, wobble=2)
    a, b = _run(f), _run(f)
    assert a is not None and b is not None
    assert (a.effect_rub_month, a.ci_low_rub_month, a.ci_high_rub_month) == (
        b.effect_rub_month,
        b.ci_low_rub_month,
        b.ci_high_rub_month,
    )


def test_a_fall_the_controls_had_too_is_no_effect() -> None:
    both = {(R1, TOMATO): D("0.05"), (R2, TOMATO): D("0.05"), (R3, TOMATO): D("0.05")}
    res = _run(_facts({(R1, TOMATO): D("0.10"), (R2, TOMATO): D("0.10"), (R3, TOMATO): D("0.10")}, both))
    assert res is not None and res.effect == 0 and res.verdict == "rejected"


def test_a_small_fall_in_noisy_days_is_the_right_direction_but_not_significant() -> None:
    res = _run(_facts({(R1, TOMATO): D("0.10")}, {(R1, TOMATO): D("0.095")}, wobble=8))
    assert res is not None and res.effect_rub_month > 0 and res.verdict == "inconclusive"
    assert res.ci_low_rub_month <= 0 < res.ci_high_rub_month


def test_within_the_restaurant_other_products_are_the_control_and_before_after_is_weak() -> None:
    f = _facts({(R1, TOMATO): D("0.10")}, {(R1, TOMATO): D("0.05")}, wobble=1)
    items = _run(f, "items", [Unit(R1, frozenset({CUCUMBER}))])
    assert items is not None and items.verdict == "confirmed" and items.control_before == D("0.03")
    alone = _run(f, "before_after", [])
    assert alone is not None and alone.weak and alone.control_before is None and alone.effect == D("-0.05")


def test_no_rows_after_the_start_is_no_measurement_yet() -> None:
    f = _facts({}, {})
    f.write_offs = [w for w in f.write_offs if w.day < START]
    f.receipts = [r for r in f.receipts if r.day < START]
    assert _run(f) is None


def test_the_smallest_visible_effect_grows_with_the_noise() -> None:
    quiet, noisy = _facts({}, {}, wobble=1), _facts({}, {}, wobble=6)
    args = (Spec("writeoffs", TOMATO), "restaurants", Unit(R1), [Unit(R2), Unit(R3)], (BEFORE[0], AFTER[1]))
    a = mde_rub_month(quiet, _usage(quiet), *args, seed=7)
    b = mde_rub_month(noisy, _usage(noisy), *args, seed=7)
    assert a is not None and b is not None and 0 < a < b


def test_the_forecast_credits_only_the_change_and_for_overuse_only_the_excess() -> None:
    """Code review of stage 7, p. 4: the test fell 10% → 5%, the control 8% → 6%: the change's share is
    3 p.p. of 10% = 30%, not 50%. Another restaurant at 4% would save 30% of its 4%."""
    from app.analytics.measure import Result, forecast_rub_month

    f = _facts(
        {(R1, TOMATO): D("0.10"), (R2, TOMATO): D("0.08")}, {(R1, TOMATO): D("0.05"), (R2, TOMATO): D("0.06")}
    )
    usage = _usage(f)
    r = measure(
        f, usage, Spec("writeoffs", TOMATO), "restaurants", Unit(R1), [Unit(R2)], BEFORE, AFTER, seed=7
    )
    assert r is not None and r.effect == D("-0.03")
    # R3 writes off its usual 3%: 30% of it, on 300 kg a month at 200 ₽ → 0.009 × 60 000 = 540 ₽
    assert forecast_rub_month(f, usage, Spec("writeoffs", TOMATO), r, [R3], AFTER) == D(540)
    over = Result(
        "restaurants",
        BEFORE,
        AFTER,
        28,
        D("1.30"),
        D("1.10"),
        D(1),
        D(1),
        D("-0.20"),
        D(1),
        D(0),
        D(2),
        "confirmed",
        False,
        D(1),
    )
    # a restaurant already at its recipes (1.00) has no room: nothing to forecast
    assert forecast_rub_month(f, usage, Spec("overuse", TOMATO), over, [], AFTER) == 0


def test_rubles_a_month_count_the_days_with_sales_not_the_calendar() -> None:
    """Code review of stage 7, p. 5: 7 days of sales in a 28-day «before» are a week, not four."""
    from app.analytics.facts import SaleRow
    from app.analytics.measure import active_days

    f = _facts({}, {})
    dish = uuid4()
    f.sales = [SaleRow(R1, BEFORE[0] + timedelta(days=i), dish, D(1), D(100), D(0), None) for i in range(7)]
    assert active_days(f, R1, BEFORE) == 7 and active_days(f, R2, BEFORE) == 28  # no sales: the calendar


def test_a_cashier_is_compared_with_whole_restaurants_or_the_others_of_the_same_one() -> None:
    """Code review of stage 7, p. 2: «таб. 104» is not in R02 — R02 as a whole is the control."""
    from app.analytics.facts import SaleRow

    f = _facts({}, {})
    dish = uuid4()
    for i in range(56):
        day = BEFORE[0] + timedelta(days=i)
        share = D("0.12") if day < START else D("0.03")
        f.sales += [
            SaleRow(R1, day, dish, D(1), D(1000) * (1 - share), D(1000) * share, "таб. 104"),
            SaleRow(R1, day, dish, D(1), D(970), D(30), "таб. 101"),
            SaleRow(R2, day, dish, D(1), D(970), D(30), "таб. 201"),
        ]
    usage, spec = _usage(f), Spec("discounts", cashier="таб. 104")
    whole = measure(f, usage, spec, "restaurants", Unit(R1), [Unit(R2, whole=True)], BEFORE, AFTER, seed=7)
    peers = measure(f, usage, spec, "items", Unit(R1), [Unit(R1, others=True)], BEFORE, AFTER, seed=7)
    assert whole is not None and whole.control_before == D("0.03") and whole.verdict == "confirmed"
    assert peers is not None and peers.control_before == D("0.03") and peers.effect == D("-0.09")
    # the cashier alone in another restaurant would be no control at all
    assert measure(f, usage, spec, "restaurants", Unit(R1), [Unit(R2)], BEFORE, AFTER, seed=7) is None


def test_the_smallest_visible_effect_falls_with_a_longer_check() -> None:
    from app.analytics.measure import mde_by_weeks

    f = _facts({}, {}, wobble=3)
    by = mde_by_weeks(
        f,
        _usage(f),
        Spec("writeoffs", TOMATO),
        "restaurants",
        Unit(R1),
        [Unit(R2), Unit(R3)],
        (BEFORE[0], AFTER[1]),
        7,
        [2, 4, 6],
    )
    assert by is not None and by[2] > by[4] > by[6] > 0


def test_a_price_is_written_to_the_kopeck() -> None:
    from app.experiments.measurement import _num

    assert _num(D("212.4"), "price") == "212,40\xa0₽" and _num(D("0.4"), "price") == "0,40\xa0₽"
