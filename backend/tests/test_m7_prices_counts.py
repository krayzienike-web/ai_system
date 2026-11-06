"""M7, stage 6.5 (docs/12): invoice lines with no price or a price far off the network's, and a count without
products the restaurant usually counts (TC-ENG-34)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.analytics import m7, views
from app.analytics.facts import CountRow, Facts, ProductInfo, ReceiptRow

D = Decimal
END = date(2026, 10, 18)
R1, R2 = uuid4(), uuid4()
CHEESE, OIL = uuid4(), uuid4()


def _facts() -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02"}
    f.products = {
        CHEESE: ProductInfo("P02", "Сыр Пармезан", "Сыры", "kg", 60, False),
        OIL: ProductInfo("P14", "Масло оливковое", "Бакалея", "l", 365, False),
    }
    for k in range(8):  # a purchase a week of each product, at the usual price
        day = END - timedelta(days=7 * k)
        for r in (R1, R2):
            f.receipts += [
                ReceiptRow(r, day, CHEESE, None, D(2), D(3300)),
                ReceiptRow(r, day, OIL, None, D(5), D(5500)),
            ]
    return f


def test_a_line_with_no_amount_and_one_priced_per_gram_are_found() -> None:
    f = _facts()
    f.receipts += [
        ReceiptRow(
            R1, END - timedelta(days=3), CHEESE, None, D(2), D("3.30")
        ),  # 1,65 ₽ a kilo: a price per gram
        ReceiptRow(R1, END - timedelta(days=2), OIL, None, D(5), D(0)),  # no amount
        ReceiptRow(R1, END - timedelta(days=60), OIL, None, D(5), D(0)),  # before the 4 weeks: not looked at
        ReceiptRow(R2, END - timedelta(days=1), CHEESE, None, D(2), D(4500)),  # dearer, but within 3 times
    ]
    drafts = [d for d in m7.detect(f) if d.evidence["kind"] == "prices"]
    assert [d.key for d in drafts] == ["M7:R01:prices:P02-P14"]
    d = drafts[0]
    assert d.title == "Цены в накладных похожи на ошибку: 2 строки" and d.effect_rub_month is None
    why = {x["product"]: x["why"] for x in d.evidence["lines"]}
    assert why == {"P02": "в 1000 раз дешевле обычной", "P14": "нет суммы"}
    assert d.headline.startswith("15.10 «Сыр Пармезан»: 1,65\xa0₽ за кг — в 1000 раз дешевле обычной")
    v = views.build(d, f)
    assert v is not None and v["metric"]["value"] == "2" and len(v["table"]["rows"]) == 2


def test_ordinary_prices_give_no_finding() -> None:
    assert [d for d in m7.detect(_facts()) if d.evidence["kind"] == "prices"] == []


def _counts(products_by_day: dict[date, list]) -> list[CountRow]:  # type: ignore[type-arg]
    return [CountRow(R1, day, p, None, D(1)) for day, ps in products_by_day.items() for p in ps]


def test_a_count_without_products_counted_every_time_before_is_found() -> None:
    f = _facts()
    days = [END - timedelta(days=d) for d in (70, 40, 10)]
    f.counts = _counts({days[0]: [CHEESE, OIL], days[1]: [CHEESE, OIL], days[2]: [OIL]})
    (d,) = [d for d in m7.detect(f) if d.evidence["kind"] == "partial"]
    assert d.key == "M7:R01:partial:P02" and d.evidence["missing"] == ["P02"]
    assert d.title == "Инвентаризация 08.10 без части товаров: 1" and "сыр пармезан" in d.headline
    v = views.build(d, f)
    assert v is not None and v["table"]["rows"] == [["Сыр Пармезан"]]


def test_a_product_counted_only_sometimes_or_no_longer_bought_is_no_finding() -> None:
    f = _facts()
    days = [END - timedelta(days=d) for d in (70, 40, 10)]
    f.counts = _counts({days[0]: [OIL], days[1]: [CHEESE, OIL], days[2]: [OIL]})  # cheese not counted always
    assert [d for d in m7.detect(f) if d.evidence["kind"] == "partial"] == []
    f.counts = _counts({days[0]: [CHEESE, OIL], days[1]: [CHEESE, OIL], days[2]: [OIL]})
    f.receipts = [r for r in f.receipts if r.product != CHEESE]  # no longer bought: nothing to count
    assert [d for d in m7.detect(f) if d.evidence["kind"] == "partial"] == []
    f.counts = _counts({days[1]: [CHEESE, OIL], days[2]: [OIL]})  # one count before: too little to know
    assert [d for d in m7.detect(f) if d.evidence["kind"] == "partial"] == []
