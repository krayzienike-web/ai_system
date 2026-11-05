"""M6 overstock from «Остатки на дату» (stage 6.5, docs/12, TC-ENG-29)."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.analytics import m6, views
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow, StockRow
from app.analytics.params import DEFAULT
from app.analytics.usage import Usage
from app.catalog.recipes import Line

D = Decimal
END = date(2026, 10, 18)
DAYS = [END - timedelta(days=i) for i in range(28)]


def _facts(stock: str, bought_per_week: str = "10") -> tuple[Facts, object]:
    f = Facts()
    r, cream, pasta = uuid4(), uuid4(), uuid4()
    f.restaurants = {r: "R06"}
    f.products = {cream: ProductInfo("P04", "Сливки 33%", "Молочные", "l", 7, False)}
    f.menu = {pasta: MenuInfo("M05", "Паста", "Паста", D(600))}
    f.recipe_lines = [Line(pasta, cream, D("0.1"), date(2026, 1, 1))]
    # 10 portions a day: 1 l of cream a day
    f.sales = [SaleRow(r, d, pasta, D(10), D(6000)) for d in DAYS]
    f.receipts = [
        ReceiptRow(r, d, cream, None, D(bought_per_week), D(bought_per_week) * 360)
        for d in DAYS
        if d.weekday() == 0
    ]
    f.stock = [StockRow(r, d, cream, D(stock)) for d in DAYS]
    return f, r


def test_stock_lasting_far_longer_than_the_shelf_life_is_overstock() -> None:
    f, r = _facts("14", bought_per_week="10")
    (d,) = m6.detect_overstock(f, Usage(f), [])
    assert d.key == "M6:R06:P04:overstock" and d.restaurant == r and d.process == "planning"
    ev = d.evidence
    assert ev["cover_days"] == "14.0" and ev["shelf_life_days"] == 7 and ev["excess"] == "7.000"
    # 7 l beyond the shelf life would spoil 30/7 times a month (30 l), but only 40 − 28 = 12 l were bought
    # beyond the use in 28 days: 12 × 30 / 28 ≈ 12.86 l × 360 ₽ = 4 629 ₽
    assert ev["over_bought"] == "12.000" and d.effect_rub_month == D(4629)
    assert "≈ 14 дн. расхода при сроке годности 7 дн." in d.headline
    view = views.build(d, f)
    assert view is not None and view["metric"]["benchmark"] == "срок годности 7 дн."
    # It is found by the module's detect too
    assert [x.key for x in m6.detect(f, Usage(f), [])] == ["M6:R06:P04:overstock"]


def test_stock_within_the_shelf_life_or_too_few_snapshots_is_no_finding() -> None:
    f, _ = _facts("9")  # 9 days of use < 1.5 × 7
    assert m6.detect_overstock(f, Usage(f), []) == []
    f, _ = _facts("14")
    f.stock = f.stock[:5]
    assert m6.detect_overstock(f, Usage(f), []) == []
    f, _ = _facts("14")
    assert m6.detect_overstock(f, Usage(f), [], replace(DEFAULT, M6_MATERIALITY_RUB_MONTH=D(10000))) == []


def test_nothing_bought_beyond_the_use_is_no_finding() -> None:
    """What sits on the books but is not over-bought does not spoil month after month (the books may lag)."""
    f, _ = _facts("14", bought_per_week="7")
    assert m6.detect_overstock(f, Usage(f), []) == []


def test_products_without_shelf_life_or_purchases_are_skipped() -> None:
    f, _ = _facts("14")
    f.receipts = []
    assert m6.detect_overstock(f, Usage(f), []) == []
    f, _ = _facts("14")
    ((pid, info),) = f.products.items()
    f.products[pid] = ProductInfo(info.code, info.name, info.category, info.unit, None, False)
    assert m6.detect_overstock(f, Usage(f), []) == []
