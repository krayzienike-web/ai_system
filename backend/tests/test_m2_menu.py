"""M2 «Меню-инжиниринг» (stage 6.5, docs/12): popularity × margin of a dish within its menu category —
a popular dish with a low margin, a rarely ordered dish with a high margin (TC-ENG-32)."""

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.analytics import m2, views
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow
from app.catalog.recipes import Line

D = Decimal
END = date(2026, 10, 18)
R1, MEAT = uuid4(), uuid4()
STEAK, CUTLETS, LOBSTER, SOUP = uuid4(), uuid4(), uuid4(), uuid4()


def _facts(per_day: Mapping[UUID, object], cutlets_price: int = 500) -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01"}
    f.products = {MEAT: ProductInfo("P01", "Мясо", "Мясо", "kg", 5, False)}
    f.menu = {
        STEAK: MenuInfo("M01", "Стейк", "Горячее", D(1000)),
        CUTLETS: MenuInfo("M02", "Котлеты", "Горячее", D(cutlets_price)),
        LOBSTER: MenuInfo("M03", "Омар", "Горячее", D(1500)),
        SOUP: MenuInfo("M04", "Суп", "Супы", D(400)),
    }
    f.receipts = [ReceiptRow(R1, END, MEAT, None, D(10), D(1000))]  # 100 ₽ a unit
    since = date(2026, 1, 1)
    f.recipe_lines = [
        Line(STEAK, MEAT, D(2), since),  # margin 1000 − 200 = 800
        Line(CUTLETS, MEAT, D(1), since),  # 500 − 100 = 400
        Line(LOBSTER, MEAT, D(3), since),  # 1500 − 300 = 1200
        Line(SOUP, MEAT, D("0.5"), since),  # alone in its category
    ]
    f.sales = [
        SaleRow(
            R1, END - timedelta(days=i), item, D(str(q)), D(str(q)) * (f.menu[item].price or D(0)), D(0), None
        )
        for i in range(28)
        for item, q in per_day.items()
    ]
    return f


USUAL = {STEAK: 10, CUTLETS: 20, LOBSTER: 3, SOUP: 5}


def test_a_popular_dish_with_a_low_margin_and_a_rare_one_with_a_high_margin_are_found() -> None:
    f = _facts(USUAL)
    by_key = {d.key: d for d in m2.detect_menu(f)}
    assert set(by_key) == {"M2:net:M02:plowhorse", "M2:net:M03:puzzle"}
    cutlets = by_key["M2:net:M02:plowhorse"]
    assert cutlets.kind == "opportunity" and cutlets.restaurant is None and cutlets.process == "planning"
    # 61% of the category, 400 ₽ a portion against 594 ₽ on average; 500 × 1.05 → 530 ₽ in the next menu:
    # 30 ₽ × 560 portions × 0.5 over 28 days → 9 000 ₽ a month
    assert cutlets.evidence["margin"] == "400.00" and cutlets.evidence["category_margin"] == "593.94"
    assert cutlets.evidence["new_price"] == "530" and cutlets.effect_rub_month == D(9000)
    assert "530\xa0₽ вместо 500\xa0₽" in cutlets.headline
    lobster = by_key["M2:net:M03:puzzle"]
    # 9% of the category at 1 200 ₽ a portion; the others earn 533 ₽: 8.4 more portions × 667 ₽ → 6 000 ₽
    assert lobster.evidence["others_margin"] == "533.33" and lobster.effect_rub_month == D(6000)
    assert "блюдо берут редко: 9% продаж" in lobster.headline


def test_a_balanced_menu_and_a_dish_alone_in_its_category_give_nothing() -> None:
    # the cutlets at 560 ₽: their margin is no longer far below the category's
    assert [d.key for d in m2.detect_menu(_facts(USUAL, cutlets_price=560))] == ["M2:net:M03:puzzle"]
    assert m2.detect_menu(_facts({STEAK: 10, CUTLETS: 10, SOUP: 5}, cutlets_price=900)) == []
    assert m2.detect_menu(Facts()) == []


def test_small_sums_and_dishes_already_found_by_food_cost_are_skipped() -> None:
    tiny = {STEAK: 1, CUTLETS: 2, LOBSTER: D("0.3"), SOUP: 1}
    assert m2.detect_menu(_facts(tiny)) == []  # under 3 000 ₽ a month
    f = _facts(USUAL)
    covered = [d for d in m2.detect_menu(f) if d.evidence["menu_item"] == "M02"]
    assert [d.key for d in m2.detect_menu(f, covered=covered)] == ["M2:net:M03:puzzle"]


def test_the_menu_findings_are_shown_with_the_category() -> None:
    f = _facts(USUAL)
    d = next(d for d in m2.detect_menu(f) if d.evidence["kind"] == "plowhorse")
    v = views.build(d, f)
    assert v is not None and v["metric"]["value"] == "400 ₽"
    assert v["metric"]["benchmark"] == "в среднем по категории 594 ₽"
    assert v["table"]["title"] == "Блюда категории «Горячее»" and len(v["table"]["rows"]) == 3
