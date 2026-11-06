"""Linked findings (stage 6.5, docs/12): findings with one cause share a story; its sum is the largest one's
(TC-ENG-33)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.analytics import links
from app.analytics.drafts import Draft
from app.analytics.facts import Facts, ProductInfo

D = Decimal
R1, R2 = uuid4(), uuid4()


def _facts() -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02"}
    f.products = {
        uuid4(): ProductInfo("P04", "Сливки 33%", "Молочные", "l", 7, False),
        uuid4(): ProductInfo("P09", "Лосось охлажденный", "Рыба", "kg", 4, False),
    }
    return f


def _d(key: str, module: str, restaurant: object, effect: int | None, **evidence: object) -> Draft:
    return Draft(
        key=key,
        module=module,
        kind="opportunity" if module == "M2" else "problem",
        process="planning",
        restaurant=restaurant,  # type: ignore[arg-type]
        title=key,
        headline="",
        effect_rub_month=None if effect is None else D(effect),
        effect_note=None,
        confidence="medium",
        period_from=date(2026, 9, 21),
        period_to=date(2026, 10, 18),
        evidence=dict(evidence),
    )


def test_overstock_and_write_offs_of_one_product_in_one_restaurant_are_one_story() -> None:
    over = _d("M6:R01:P04:overstock", "M6", R1, 21253, kind="overstock", product="P04")
    waste = _d("M5:R01:P04", "M5", R1, 21220, product="P04")
    elsewhere = _d("M5:R02:P04", "M5", R2, 9000, product="P04")  # another restaurant: its own story or none
    links.link([over, waste, elsewhere], _facts())
    assert over.story_key == waste.story_key == "supply:R01:P04"
    assert over.story_title == "Закупают больше, чем успевают использовать: Сливки 33%"
    assert elsewhere.story_key is None
    assert links.story_sum([over.effect_rub_month, waste.effect_rub_month]) == D(21253)  # not 42 473


def test_two_findings_of_the_same_side_are_no_story() -> None:
    a = _d("M5:R01:P04", "M5", R1, 100, product="P04")
    b = _d("M5:R01:P04:weekdays", "M5", R1, 200, product="P04")
    links.link([a, b], _facts())
    assert a.story_key is None and b.story_key is None


def test_a_network_price_rise_joins_the_dishes_it_made_dearer() -> None:
    rise = _d("M3:net:P09:growth", "M3", None, 542934, kind="growth", product="P09")
    salmon = [{"product": "P09", "qty": "0.2", "price": "2028", "price_before": "1451"}]
    cream = [{"product": "P04", "qty": "0.08", "price": "400", "price_before": "360"}]
    dish = _d("M2:net:M07", "M2", None, 36501, menu_item="M07", ingredients=salmon + cream)
    other = _d("M2:net:M03", "M2", None, 5000, menu_item="M03", ingredients=cream)  # driven by cream
    links.link([rise, dish, other], _facts())
    assert rise.story_key == dish.story_key == "price:net:P09"
    assert dish.story_title == "Подорожал лосось охлажденный: вырос фудкост блюд"
    assert other.story_key is None


def test_missing_invoices_and_a_dearer_purchase_link_their_pairs() -> None:
    under = _d("M1:R01:P04:under", "M1", R1, None, product="P04")
    negative = _d("M7:R01:P04:negative", "M7", R1, None, kind="negative", product="P04")
    over = _d("M1:R02:P04", "M1", R2, 5000, product="P04")
    dearer = _d("M3:R02:P04:jump", "M3", R2, 4000, kind="jump", product="P04")
    links.link([under, negative, over, dearer], _facts())
    assert under.story_key == negative.story_key == "receipts:R01:P04"
    assert over.story_key == dearer.story_key == "supplier:R02:P04"
    assert links.story_sum([None, None]) is None
