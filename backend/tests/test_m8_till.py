"""M8 «Касса» (stage 6.5, docs/12): removals after the check was printed and discounts, by cashier
(TC-ENG-27, TC-ENG-28)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.analytics import m8
from app.analytics.facts import Facts, MenuInfo, SaleRow, VoidRow

D = Decimal
END = date(2026, 10, 18)
R1, R2, R3 = uuid4(), uuid4(), uuid4()
DISH = uuid4()


def _facts(voids: list[VoidRow], sales: list[SaleRow]) -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.menu = {DISH: MenuInfo("M01", "Пицца", "Пицца", D(580))}
    f.voids, f.sales = voids, sales
    return f


def _days(n: int = 28) -> list[date]:
    return [END - timedelta(days=i) for i in range(n)]


def _sales(restaurant: UUID, cashier: str | None, discount_share: str = "0.03") -> list[SaleRow]:
    gross = D(10000)
    discount = (gross * D(discount_share)).quantize(D("0.01"))
    return [SaleRow(restaurant, d, DISH, D(10), gross - discount, discount, cashier) for d in _days()]


def _voids(restaurant: UUID, cashier: str, per_week: int, after_print: bool = True) -> list[VoidRow]:
    return [
        VoidRow(restaurant, d, D(580), cashier, after_print)
        for i, d in enumerate(_days())
        if i % 7 < per_week
    ]


def test_a_cashier_removing_after_printing_far_more_than_the_others_is_found() -> None:
    voids = _voids(R1, "таб. 103", 5) + _voids(R1, "таб. 101", 1) + _voids(R2, "таб. 201", 1)
    voids += _voids(R3, "таб. 301", 1) + _voids(R2, "таб. 202", 7, after_print=False)  # before printing: fine
    sales = _sales(R1, "таб. 103") + _sales(R1, "таб. 101") + _sales(R2, "таб. 201") + _sales(R3, "таб. 301")
    drafts = [d for d in m8.detect(_facts(voids, sales)) if d.evidence["kind"] == "voids"]
    assert [d.key for d in drafts] == ["M8:R01:voids:таб. 103"]
    d = drafts[0]
    assert d.restaurant == R1 and d.module == "M8" and d.process == "accounting"
    assert d.evidence["count"] == 20 and d.evidence["network_median"] == "2320.00"
    # 20 × 580 = 11 600 against the median cashier's 4 × 580 = 2 320: 9 280 over 28 days → 9 943 a month
    assert d.effect_rub_month == D(9943)
    assert "таб. 103" in d.headline and "после печати пречека" in d.headline


def test_a_few_removals_are_no_finding() -> None:
    voids = _voids(R1, "таб. 103", 1) + _voids(R2, "таб. 201", 1) + _voids(R3, "таб. 301", 1)
    sales = _sales(R1, "таб. 103") + _sales(R2, "таб. 201") + _sales(R3, "таб. 301")
    assert m8.detect(_facts(voids, sales)) == []


def test_a_cashier_with_far_larger_discounts_is_found_with_the_excess() -> None:
    sales = (
        _sales(R1, "таб. 104", "0.12")
        + _sales(R1, "таб. 101")
        + _sales(R2, "таб. 201")
        + _sales(R3, "таб. 301", "0.02")
    )
    drafts = m8.detect(_facts([], sales))
    assert [d.key for d in drafts] == ["M8:R01:discounts:таб. 104"]
    d = drafts[0]
    # 12% against the median cashier's 3%: 9 p.p. of 280 000 ₽ gross over 28 days → 27 000 a month
    assert d.evidence["share"] == "0.1200" and d.evidence["network_share"] == "0.0300"
    assert d.effect_rub_month == D(27000)


def test_without_cashiers_the_restaurant_is_compared_with_the_network() -> None:
    sales = _sales(R1, None, "0.12") + _sales(R2, None) + _sales(R3, None, "0.02")
    drafts = m8.detect(_facts([], sales))
    assert [d.key for d in drafts] == ["M8:R01:discounts"]
    assert drafts[0].title == "Скидки выше сети: R01"


def test_no_till_data_no_finding() -> None:
    assert m8.detect(_facts([], [])) == []


def test_till_findings_are_shown_with_their_numbers() -> None:
    from app.analytics import views

    voids = _voids(R1, "таб. 103", 5) + _voids(R1, "таб. 101", 1) + _voids(R2, "таб. 201", 1)
    voids += _voids(R3, "таб. 301", 1)
    sales = (
        _sales(R1, "таб. 103", "0.12")
        + _sales(R1, "таб. 101")
        + _sales(R2, "таб. 201")
        + _sales(R3, "таб. 301", "0.02")
    )
    f = _facts(voids, sales)
    by_kind = {d.evidence["kind"]: d for d in m8.detect(f)}
    v = views.build(by_kind["voids"], f)
    assert (
        v is not None
        and v["metric"]["value"] == "11 600 ₽"
        and v["metric"]["benchmark"] == "обычный кассир 2 320 ₽"
    )
    s = views.build(by_kind["discounts"], f)
    assert s is not None and s["metric"]["value"] == "12%" and s["scale"]["network"] == 3.0
    places = m8.detect(_facts([], _sales(R1, None, "0.12") + _sales(R2, None) + _sales(R3, None, "0.02")))
    r = views.build(places[0], f)
    assert r is not None and r["confidence_note"] == "Продажи r_keeper со скидками"


def test_restaurants_without_the_export_are_not_the_typical_cashier() -> None:
    """Code review of stage 6.5, p. 2: only R01 loads «Удаления и отмены»; the cashiers of R02 and R03 have no
    voids because nobody exported them — they must not make R01's ordinary cashiers look suspicious."""
    voids = _voids(R1, "таб. 101", 2) + _voids(R1, "таб. 102", 2)
    sales = _sales(R1, "таб. 101") + _sales(R1, "таб. 102") + _sales(R2, "таб. 201") + _sales(R3, "таб. 301")
    assert [d for d in m8.detect(_facts(voids, sales)) if d.evidence["kind"] == "voids"] == []
    # Without a discount column (all zeros) a restaurant is no benchmark for the discounts either.
    no_discounts = _sales(R2, "таб. 201", "0") + _sales(R3, "таб. 301", "0")
    sales = _sales(R1, "таб. 101", "0.12") + _sales(R1, "таб. 102", "0.03") + no_discounts
    assert m8.detect(_facts([], sales)) == []
