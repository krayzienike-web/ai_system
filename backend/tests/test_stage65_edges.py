"""Stage 6.5 engine (docs/12): thresholds exactly at the limit, empty and odd inputs, ties — the end-of-stage
test pass after the code review of 06.11.2026 (TC-ENG-38…42)."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.analytics import links, m2, m3, m6, m7, m8, quality
from app.analytics.drafts import Draft
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow, StockRow, VoidRow
from app.analytics.params import DEFAULT
from app.analytics.usage import Usage
from app.catalog.recipes import Line
from app.insights.models import Finding
from app.insights.money import counted
from app.overview.service import Kpis, _data_quality_answer

D = Decimal
END = date(2026, 10, 18)
DAYS = [END - timedelta(days=i) for i in range(28)]
R1, R2, R3 = uuid4(), uuid4(), uuid4()


# --- M2 menu engineering: popularity and materiality exactly at the limit (TC-ENG-38) ---


def _menu(per_day_a: str, per_day_b: str, price_a: int, meat_a: int) -> Facts:
    """Two dishes in «Горячее»: A at `price_a` with `meat_a` units of meat (100 ₽ each), B at 1 100 ₽
    with one."""
    f = Facts()
    meat, a, b = uuid4(), uuid4(), uuid4()
    f.restaurants = {R1: "R01"}
    f.products = {meat: ProductInfo("P01", "Мясо", "Мясо", "kg", 5, False)}
    f.menu = {
        a: MenuInfo("M01", "Котлеты", "Горячее", D(price_a)),
        b: MenuInfo("M02", "Стейк", "Горячее", D(1100)),
    }
    f.receipts = [ReceiptRow(R1, END, meat, None, D(10), D(1000))]  # 100 ₽ a unit
    f.recipe_lines = [Line(a, meat, D(meat_a), date(2026, 1, 1)), Line(b, meat, D(1), date(2026, 1, 1))]
    f.sales = [
        SaleRow(R1, day, item, D(q), D(q) * (f.menu[item].price or D(0)))
        for day in DAYS
        for item, q in ((a, per_day_a), (b, per_day_b))
    ]
    return f


def test_m2_a_dish_at_exactly_seventy_percent_of_an_equal_share_is_popular() -> None:
    # Two dishes: an equal share is 50%, popular from 0.7 × 50% = 35% («не меньше»).
    # A: 7 a day of 20 → 196 of 560 portions = exactly 35%; margin 1 000 − 700 = 300 ₽,
    # B: margin 1 100 − 100 = 1 000 ₽; the category's average (196 × 300 + 364 × 1 000) / 560 = 755 ₽,
    # 300 < 0.7 × 755 = 528.5 → low. Next menu 1 000 × 1.05 = 1 050 ₽ (already a multiple of 10):
    # 50 ₽ × 196 portions × 0.5 = 4 900 ₽ over 28 days → 4 900 × 30 / 28 = 5 250 ₽ a month.
    (d,) = m2.detect_menu(_menu("7", "13", 1000, 7))
    assert d.key == "M2:net:M01:plowhorse" and d.evidence["share"] == "0.3500"
    assert d.evidence["category_margin"] == "755.00" and d.evidence["new_price"] == "1050"
    assert d.effect_rub_month == D(5250)
    # 6.9 a day → 193.2 of 560 = 34.5%: below 35%, not popular; nor a high margin → nothing.
    assert m2.detect_menu(_menu("6.9", "13.1", 1000, 7)) == []


def test_m2_a_sum_of_exactly_three_thousand_a_month_is_shown() -> None:
    # A at 400 ₽ (margin 300), 10 a day; B 15 a day (margin 1 000): share 280 / 700 = 40% ≥ 35%,
    # average (280 × 300 + 420 × 1 000) / 700 = 720, 300 < 504 → low. 400 × 1.05 = 420 ₽:
    # 20 ₽ × 280 × 0.5 = 2 800 ₽ over 28 days → 2 800 × 30 / 28 = 3 000 ₽ — «от 3 000 ₽» is shown.
    f = _menu("10", "15", 400, 1)
    (d,) = m2.detect_menu(f)
    assert d.evidence["new_price"] == "420" and d.effect_rub_month == D(3000)
    assert m2.detect_menu(f, replace(DEFAULT, M2_MATERIALITY_RUB_MONTH=D(3001))) == []


def test_m2_no_sales_or_no_prices_give_nothing() -> None:
    f = _menu("10", "15", 400, 1)
    assert m2.detect_menu(replace(f, sales=[])) == []
    assert m2.detect_menu(replace(f, receipts=[])) == []
    # a return (negative quantity) is no purchase price (code review of stage 6.5, p. 9)
    (meat,) = f.products
    returned = replace(f, receipts=[ReceiptRow(R1, END, meat, None, D(-10), D(-1000))])
    assert m2.detect_menu(returned) == []


# --- M3 price jump: exactly 10 % over its own history (TC-ENG-39) ---


def _jump(now_price: int) -> Facts:
    f = Facts()
    cheese = uuid4()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.products = {cheese: ProductInfo("P01", "Сыр Моцарелла", "Сыры", "kg", 10, False)}
    for k in range(16):  # 100 kg a week; the last 4 weeks are the window, the 12 before — its own history
        day = END - timedelta(days=7 * k)
        price = now_price if k < 4 else 500
        f.receipts.append(ReceiptRow(R1, day, cheese, None, D(100), D(100 * price)))
        for r in (R2, R3):
            f.receipts.append(ReceiptRow(r, day, cheese, None, D(100), D(100 * 600)))
    return f


def test_m3_a_rise_of_exactly_ten_percent_is_no_jump() -> None:
    # 550 / 500 − 1 = 10%, the others 0%: «больше 10%» is not met
    # (the sum would be 50 × 400 × 30 / 28 = 21 429)
    assert m3.detect_jumps(_jump(550)) == []
    # 551 / 500 − 1 = 10.2% > 10%: (551 − 500) × 400 kg = 20 400 over 28 days → 20 400 × 30 / 28 = 21 857
    (d,) = m3.detect_jumps(_jump(551))
    assert d.evidence["growth"] == "0.1020" and d.effect_rub_month == D(21857)


def test_m3_returns_are_no_purchases_of_the_jump() -> None:
    f = _jump(551)
    (cheese,) = f.products
    # a return in the window at a silly price changes nothing: only purchases (qty > 0) make the price
    f.receipts.append(ReceiptRow(R1, END, cheese, None, D(-5), D(-50000)))
    (d,) = m3.detect_jumps(f)
    assert d.evidence["price"] == "551.00" and d.effect_rub_month == D(21857)


# --- M6 overstock: the books below zero, semi-finished products, the minimum of snapshots (TC-ENG-40) ---


def _overstock(stock: list[str], is_semi: bool = False) -> Facts:
    """1 l of cream a day by the recipes, 10 l bought each Monday (4 Mondays: 40 l), 360 ₽ a litre."""
    f = Facts()
    cream, pasta = uuid4(), uuid4()
    f.restaurants = {R1: "R06"}
    f.products = {cream: ProductInfo("P04", "Сливки 33%", "Молочные", "l", 7, is_semi)}
    f.menu = {pasta: MenuInfo("M05", "Паста", "Паста", D(600))}
    f.recipe_lines = [Line(pasta, cream, D("0.1"), date(2026, 1, 1))]
    f.sales = [SaleRow(R1, d, pasta, D(10), D(6000)) for d in DAYS]
    f.receipts = [ReceiptRow(R1, d, cream, None, D(10), D(3600)) for d in DAYS if d.weekday() == 0]
    f.stock = [StockRow(R1, d, cream, D(q)) for d, q in zip(DAYS, stock, strict=False)]
    return f


def test_m6_a_stock_below_zero_on_the_books_counts_as_nothing_on_the_shelf() -> None:
    # 14 days at −10 l, 14 at 30 l. With the minus as nothing: median of 14 × 0 and 14 × 30 = 15 l → 15 days
    # of use ≥ 1.5 × 7 = 10.5 → overstock (taken as it is, the median would be 10 l: under the limit).
    f = _overstock(["-10", "30"] * 14)
    (d,) = m6.detect_overstock(f, Usage(f), [])
    assert d.evidence["stock"] == "15.000" and d.evidence["cover_days"] == "15.0"
    # 15 − 7 = 8 l over the shelf life, but only 40 − 28 = 12 l bought beyond the use:
    # 12 × 30 / 28 × 360 ₽ = 4 628.57 → 4 629 ₽ a month (the cap, below 8 × 30 / 7 × 360 = 12 343)
    assert d.evidence["excess"] == "8.000" and d.effect_rub_month == D(4629)


def test_m6_fourteen_snapshots_are_enough_thirteen_are_not() -> None:
    f = _overstock(["14"] * 14)  # median 14 l = 14 days ≥ 10.5
    assert [d.key for d in m6.detect_overstock(f, Usage(f), [])] == ["M6:R06:P04:overstock"]
    f = _overstock(["14"] * 13)
    assert m6.detect_overstock(f, Usage(f), []) == []


def test_m6_semi_finished_products_and_no_stock_export_are_skipped() -> None:
    f = _overstock(["14"] * 28, is_semi=True)
    assert m6.detect_overstock(f, Usage(f), []) == []
    f = _overstock([])
    assert m6.detect_overstock(f, Usage(f), []) == []


# --- M8 till: the count of removals and the 3 p.p. of discounts at the limit (TC-ENG-41) ---


def _till(removals: int, discount_share: str = "0.02") -> Facts:
    f = Facts()
    dish = uuid4()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    f.menu = {dish: MenuInfo("M01", "Пицца", "Пицца", D(580))}
    f.voids = [VoidRow(R1, DAYS[i], D(580), "таб. 105", True) for i in range(removals)]
    f.voids += [
        VoidRow(r, DAYS[0], D(580), c, True)
        for r, c in ((R1, "таб. 101"), (R2, "таб. 201"), (R3, "таб. 301"))
    ]
    for r, c, share in ((R1, "таб. 105", discount_share), (R1, "таб. 101", "0.02"), (R2, "таб. 201", "0.02")):
        f.sales += [
            SaleRow(r, d, dish, D(10), D(10000) - D(10000) * D(share), D(10000) * D(share), c) for d in DAYS
        ]
    f.sales += [SaleRow(R3, d, dish, D(10), D(9800), D(200), "таб. 301") for d in DAYS]
    return f


def _kinds(f: Facts, kind: str) -> list[Draft]:
    return [d for d in m8.detect(f) if d.evidence["kind"] == kind]


def test_m8_eight_removals_after_printing_are_enough_seven_are_not() -> None:
    # 8 × 580 = 4 640 ₽ against the median cashier [4 640, 580, 580, 580] → 580 ₽; 4 640 ≥ 3 × 580:
    # 4 060 over 28 days → 4 060 × 30 / 28 = 4 350 ₽ a month
    (d,) = _kinds(_till(8), "voids")
    assert d.key == "M8:R01:voids:таб. 105" and d.evidence["count"] == 8 and d.effect_rub_month == D(4350)
    # 7 removals (3 480 over the median → 3 729 ₽ a month, above 3 000 ₽) are still too few to judge
    assert _kinds(_till(7), "voids") == []


def test_m8_discounts_exactly_three_points_above_the_usual_are_found() -> None:
    # 5% against the median 2%: 2.5 times and exactly 3 p.p. («хотя бы на 3 п.п.»):
    # 280 000 ₽ before discounts × 3% = 8 400 over 28 days → 9 000 ₽ a month
    (d,) = _kinds(_till(0, "0.05"), "discounts")
    assert d.key == "M8:R01:discounts:таб. 105" and d.effect_rub_month == D(9000)
    # 4.99%: 2.5 times, but 2.99 p.p. — not enough
    assert _kinds(_till(0, "0.0499"), "discounts") == []


# --- M7 prices: exactly 3 times off, and too few lines for a typical price (TC-ENG-34) ---


def _invoices() -> tuple[Facts, UUID]:
    f = Facts()
    cheese = uuid4()
    f.restaurants = {R1: "R01", R2: "R02"}
    f.products = {cheese: ProductInfo("P02", "Сыр Пармезан", "Сыры", "kg", 60, False)}
    for k in range(8):  # 16 lines at 1 650 ₽/kg: the typical price
        for r in (R1, R2):
            f.receipts.append(ReceiptRow(r, END - timedelta(days=7 * k), cheese, None, D(2), D(3300)))
    return f, cheese


def _odd(f: Facts) -> list[Draft]:
    return [d for d in m7.detect(f) if d.evidence["kind"] == "prices"]


def test_m7_a_price_exactly_three_times_the_typical_is_no_error() -> None:
    f, cheese = _invoices()
    f.receipts += [
        ReceiptRow(
            R2, END - timedelta(days=1), cheese, None, D(2), D(9900)
        ),  # 4 950 = 3 × 1 650: «больше» no
        ReceiptRow(R2, END - timedelta(days=2), cheese, None, D(2), D(1100)),  # 550 = 1 650 / 3: no
    ]
    assert _odd(f) == []
    f.receipts.append(ReceiptRow(R1, END - timedelta(days=1), cheese, None, D(2), D(9902)))  # 4 951 > 4 950
    (d,) = _odd(f)
    assert d.key == "M7:R01:prices" and [x["price"] for x in d.evidence["lines"]] == ["4951.00"]


def test_m7_a_product_with_fewer_than_three_priced_lines_has_no_typical_price() -> None:
    f = Facts()
    oil = uuid4()
    f.restaurants = {R1: "R01"}
    f.products = {oil: ProductInfo("P14", "Масло оливковое", "Бакалея", "l", 365, False)}
    f.receipts = [ReceiptRow(R1, END - timedelta(days=d), oil, None, D(5), D(5500)) for d in (20, 10)]
    f.receipts.append(ReceiptRow(R1, END, oil, None, D(5), D(0)))  # no amount
    assert _odd(f) == []  # two priced lines: «нужны хотя бы 3 строки»
    f.receipts.append(ReceiptRow(R1, END - timedelta(days=5), oil, None, D(5), D(5500)))
    (d,) = _odd(f)
    assert [x["why"] for x in d.evidence["lines"]] == ["нет суммы"]
    assert m7.detect(Facts()) == []


# --- The data quality score: the limit of 60, caps, the floor and the average (TC-ENG-42) ---


def _dq(
    key: str, restaurant: UUID | None, kind: str, module: str = "M7", confidence: str = "high", **ev: object
) -> Draft:
    return Draft(
        key=key,
        module=module,
        kind="problem",
        process="accounting",
        restaurant=restaurant,
        title=key,
        headline="",
        effect_rub_month=None,
        effect_note=None,
        confidence=confidence,
        period_from=date(2026, 9, 21),
        period_to=date(2026, 10, 18),
        evidence={"kind": kind, **ev},
    )


def _two() -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02"}
    return f


def test_a_score_of_exactly_sixty_keeps_the_confidence_below_it_is_lowered() -> None:
    sixty = [_dq("M7:R01:sales", R1, "gap"), _dq("M4:R01:overdue", R1, "overdue", "M4")]  # 100 − 25 − 15 = 60
    loss = _dq("M1:R01:P01", R1, "", "M1")
    scores = quality.score([*sixty, loss], _two())
    assert scores[R1].score == 60
    quality.apply([*sixty, loss], scores)
    assert loss.confidence == "high" and "data_quality" not in loss.evidence  # «ниже 60»: 60 is not below
    paper = _dq("M4:R01:paper", R1, "paper", "M4")  # 100 − 25 − 20 = 55
    low, medium = _dq("M5:R01:P01", R1, "", "M5", "low"), _dq("M3:R01:P01", R1, "", "M3", "medium")
    drafts = [sixty[0], paper, low, medium]
    scores = quality.score(drafts, _two())
    quality.apply(drafts, scores)
    assert scores[R1].score == 55 and medium.confidence == "low" and low.confidence == "low"  # low stays low
    # no view: the reason is kept in the evidence, nothing to write into a card
    assert medium.evidence["data_quality"] == 55 and medium.view is None


def test_the_caps_the_floor_of_zero_and_the_networks_rounded_average() -> None:
    every = [
        _dq("M7:R01:sales", R1, "gap"),
        _dq("M7:R01:receipts", R1, "gap"),
        _dq("M7:R01:sales2", R1, "gap"),  # a third gap: 75, capped at 50
        _dq("M4:R01:paper", R1, "paper", "M4"),
        _dq("M4:R01:overdue", R1, "overdue", "M4"),
        _dq("M7:R01:partial:2026-10-01", R1, "partial"),
        _dq("M7:R01:partial:2026-09-01", R1, "partial"),  # two partial counts: 20, capped at 10
        *[_dq(f"M7:R01:P0{i}:negative", R1, "negative") for i in range(4)],
        _dq("M7:R01:prices", R1, "prices", lines=[{}] * 3),  # 15 points
    ]
    scores = quality.score(every, _two())
    points = {str(p["kind"]): p["points"] for p in scores[R1].parts}
    assert points == {"gap": 50, "paper": 20, "overdue": 15, "partial": 10, "negative": 30, "prices": 15}
    assert scores[R1].score == 0  # 100 − 140, not −40
    # R01 at 85 (overdue), R02 at 90 (partial): (85 + 90) / 2 = 87.5 → 88 (half up)
    scores = quality.score(
        [_dq("M4:R01:overdue", R1, "overdue", "M4"), _dq("M7:R02:partial:x", R2, "partial")], _two()
    )
    assert (scores[R1].score, scores[R2].score, scores[None].score) == (85, 90, 88)


def test_a_network_no_recipe_finding_takes_points_only_where_the_dish_is_sold() -> None:
    scores = quality.score([_dq("M7:net:M12", None, "no_recipe", restaurants=["R02"])], _two())
    assert scores[R1].score == 100 and scores[R2].score == 90
    assert scores[R2].parts[0]["findings"] == ["M7:net:M12"]


def test_the_answer_names_the_level_at_its_limits() -> None:
    def answer(score: int, net: int | None = None) -> str | None:
        me = Kpis(None, None, None, None, None, data_quality=score)
        return _data_quality_answer(
            me, None if net is None else Kpis(None, None, None, None, None, data_quality=net)
        )

    # 80 and above — «хорошее», 60–79 — «есть пробелы», below — «низкое» (docs/12)
    assert answer(80) == "Качество данных — 80 из 100 (хорошее)."
    assert answer(79, 83) == "Качество данных — 79 из 100 (есть пробелы), в среднем по сети 83."
    assert answer(60) == "Качество данных — 60 из 100 (есть пробелы)."
    assert answer(59) == "Качество данных — 59 из 100 (низкое)."
    assert _data_quality_answer(None, None) is None
    assert _data_quality_answer(Kpis(None, None, None, None, None), None) is None  # no score yet


# --- Linked findings: other restaurants and ties (TC-ENG-33) ---


def _link(key: str, module: str, restaurant: UUID | None, effect: int | None, kind: str = "") -> Draft:
    d = _dq(key, restaurant, kind, module, product=key.split(":")[2])
    d.effect_rub_month = None if effect is None else D(effect)
    return d


def _linked_facts() -> Facts:
    f = _two()
    f.products = {uuid4(): ProductInfo("P04", "Сливки 33%", "Молочные", "l", 7, False)}
    return f


def test_the_two_sides_of_a_story_in_two_restaurants_are_no_story() -> None:
    under = _link("M1:R01:P04:under", "M1", R1, None)
    negative = _link("M7:R02:P04:negative", "M7", R2, None, kind="negative")
    over = _link("M1:R01:P04", "M1", R1, 5000)
    jump = _link("M3:R02:P04:jump", "M3", R2, 4000, kind="jump")
    other_product = _link("M3:R01:P05:jump", "M3", R1, 4000, kind="jump")
    drafts = [under, negative, over, jump, other_product]
    links.link(drafts, _linked_facts())
    assert all(d.story_key is None for d in drafts)
    # a network-wide price rise with nothing it made dearer is no story either
    rise = _link("M3:net:P04:growth", "M3", None, 9000, kind="growth")
    links.link([rise], _linked_facts())
    assert rise.story_key is None
    links.link([], _linked_facts())  # nothing to link: no error


def test_a_story_of_two_equal_sums_counts_once_whatever_their_order() -> None:
    def f(process: str) -> Finding:
        return Finding(id=uuid4(), effect_rub_month=D(1000), story_key="supply:R01:P04", process=process)

    a, b = f("planning"), f("writeoffs")
    one, two = counted([a, b]), counted([b, a])
    assert sum(one.values()) == sum(two.values()) == D(1000)  # not 2 000
    assert one == two  # the same finding carries the story's money on every run
