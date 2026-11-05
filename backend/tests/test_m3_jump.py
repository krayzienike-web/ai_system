"""M3 «Скачок цены к своей истории» (stage 6.5, docs/12): a restaurant pays noticeably more than it used to
pay itself, beyond how the rest of the network's price moved (TC-ENG-31)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.analytics import m3, views
from app.analytics.facts import ContractRow, Facts, ProductInfo, ReceiptRow

D = Decimal
END = date(2026, 10, 18)
R1, R2, R3 = uuid4(), uuid4(), uuid4()
CHEESE, SUPPLIER = uuid4(), uuid4()


def _weekly(restaurant: UUID, before: int, now: int, weeks: int = 16) -> list[ReceiptRow]:
    """10 kg a week: at `before` ₽/kg until the last four weeks, at `now` ₽/kg in them."""
    out = []
    for k in range(weeks):
        day = END - timedelta(days=7 * k)
        price = now if k < 4 else before
        out.append(ReceiptRow(restaurant, day, CHEESE, SUPPLIER, D(10), D(10 * price)))
    return out


def _facts(receipts: list[ReceiptRow]) -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.products = {CHEESE: ProductInfo("P01", "Сыр Моцарелла", "Сыры", "kg", 10, False)}
    f.suppliers = {SUPPLIER: "Сырный дом"}
    f.receipts = receipts
    return f


def test_a_jump_only_this_restaurant_sees_is_found_while_its_price_matches_the_network() -> None:
    f = _facts(_weekly(R1, 500, 600) + _weekly(R2, 600, 600) + _weekly(R3, 600, 600))
    assert m3.detect(f) == []  # against the network R01 pays the same: the old check is silent
    drafts = m3.detect_jumps(f)
    assert [d.key for d in drafts] == ["M3:R01:P01:jump"]
    d = drafts[0]
    assert d.restaurant == R1 and d.process == "purchasing" and d.evidence["kind"] == "jump"
    assert d.evidence["growth"] == "0.2000" and d.evidence["network_growth"] == "0.0000"
    # (600 − 500) × 40 kg over 28 days → 4 286 ₽ a month
    assert d.effect_rub_month == D(4286)
    assert d.evidence["since"] == (END - timedelta(days=21)).isoformat()
    assert "«Сырный дом»" in d.headline and "у остальных ресторанов цена не изменилась" in d.headline
    v = views.build(d, f)
    assert v is not None and v["metric"]["value"] == "600.00 ₽/кг"
    assert v["metric"]["benchmark"] == "раньше 500.00 ₽/кг"


def test_a_rise_for_the_whole_network_is_no_jump_of_one_restaurant() -> None:
    f = _facts(_weekly(R1, 500, 600) + _weekly(R2, 500, 600) + _weekly(R3, 500, 590))
    assert m3.detect_jumps(f) == []


def test_the_effect_counts_only_what_is_above_the_others_rise() -> None:
    f = _facts(_weekly(R1, 500, 650) + _weekly(R2, 600, 630) + _weekly(R3, 600, 630))
    (d,) = m3.detect_jumps(f)
    # +30% against the others' +5%: (650 − 500 × 1.05) × 40 kg over 28 days → 5 357 ₽ a month
    assert d.evidence["network_growth"] == "0.0500" and d.effect_rub_month == D(5357)
    assert "у остальных ресторанов цена выросла на 5%" in d.headline


def test_small_rises_thin_history_and_covered_products_are_no_finding() -> None:
    flat = _weekly(R2, 600, 600) + _weekly(R3, 600, 600)
    assert m3.detect_jumps(_facts(_weekly(R1, 560, 600) + flat)) == []  # +7%
    assert m3.detect_jumps(_facts(_weekly(R1, 500, 600, weeks=5) + flat)) == []  # one purchase before
    f = _facts(_weekly(R1, 500, 600) + flat)
    covered = m3.detect_jumps(f)  # stands in for an overpayment against the network of the same product
    assert m3.detect_jumps(f, covered=covered) == []
    f.contracts = [ContractRow(SUPPLIER, CHEESE, D(600), date(2026, 1, 1), None)]
    assert m3.detect_jumps(f) == []  # with a contract price the contract check says it
    assert m3.detect_jumps(_facts([])) == []


def test_alone_in_the_network_the_restaurant_is_compared_with_itself() -> None:
    (d,) = m3.detect_jumps(_facts(_weekly(R1, 500, 600)))
    assert "другие рестораны этот товар не закупают" in d.headline and d.evidence["restaurants"] == 0
