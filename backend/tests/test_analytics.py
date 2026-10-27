"""Analytics engine: M1 arithmetic, decision rules, a full run on the demo network, manual review."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.analytics import engine, m1, m2, m3, m4, m5, m6, m7, views
from app.analytics.costs import CostBook
from app.analytics.facts import (
    ContractRow,
    CountRow,
    Facts,
    MenuInfo,
    ProductInfo,
    ReceiptRow,
    SaleRow,
    TransferRow,
    WriteOffRow,
)
from app.analytics.params import DEFAULT
from app.analytics.usage import Usage
from app.catalog.recipes import Line
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.core.security import hash_password
from app.demo.generator import generate
from app.demo.loader import load
from app.insights.models import Finding
from app.main import app
from app.norms.service import Norms
from app.tenancy.context import load_access_context
from app.tenancy.models import Restaurant, Role, RoleAssignment, User
from tests.conftest import PASSWORD, Network, login

D0, D1 = date(2026, 8, 3), date(2026, 10, 1)


def _facts(restaurants: int = 1) -> tuple[Facts, list[UUID], UUID, UUID]:
    f = Facts()
    rs = [uuid4() for _ in range(restaurants)]
    f.restaurants = {r: f"R{i + 1:02d}" for i, r in enumerate(rs)}
    cheese, sauce, pizza = uuid4(), uuid4(), uuid4()
    f.products = {
        cheese: ProductInfo("P01", "Сыр", "Сыры", "kg", 10, False),
        sauce: ProductInfo("P17", "Соус (п/ф)", "Заготовки", "kg", 2, True),
    }
    f.menu = {pizza: MenuInfo("M01", "Пицца", "Пицца", Decimal(580))}
    # A pizza: 0.1 kg of cheese directly and 0.05 kg of sauce, the sauce being 0.2 kg of cheese per kg.
    f.recipe_lines = [
        Line(pizza, cheese, Decimal("0.1"), date(2026, 1, 1)),
        Line(pizza, sauce, Decimal("0.05"), date(2026, 1, 1)),
        Line(sauce, cheese, Decimal("0.2"), date(2026, 1, 1)),
    ]
    return f, rs, cheese, pizza


def test_m1_arithmetic_with_semi_finished_products_transfers_and_write_offs() -> None:
    f, (r,), cheese, pizza = _facts()
    other = uuid4()
    f.sales = [SaleRow(r, D0 + timedelta(days=i), pizza, Decimal(10), Decimal(5800)) for i in range(1, 21)]
    # 200 pizzas × (0.1 + 0.05 × 0.2) = 22 kg by the recipes.
    f.receipts = [
        ReceiptRow(r, D0 + timedelta(days=5), cheese, None, Decimal(20), Decimal(12000)),
        ReceiptRow(r, D0 + timedelta(days=9), cheese, None, Decimal(10), Decimal(6600)),
        ReceiptRow(r, D0, cheese, None, Decimal(99), Decimal(1)),  # the day of the opening count: before it
    ]
    f.transfers = [
        TransferRow(other, r, D0 + timedelta(days=3), cheese, Decimal(2)),
        TransferRow(r, other, D0 + timedelta(days=4), cheese, Decimal(1)),
    ]
    f.write_offs = [WriteOffRow(r, D0 + timedelta(days=7), cheese, Decimal(1), "spoilage")]
    f.counts = [CountRow(r, D0, cheese, None, Decimal(5)), CountRow(r, D1, cheese, None, Decimal(8))]

    (row,) = m1.rows(f, Usage(f), CostBook(f.receipts))
    assert row.theory == Decimal("22.000")
    assert row.actual == Decimal(5 + 30 + 2 - 1 - 8)  # 28
    assert row.write_off == 1
    assert row.unexplained == Decimal(5)
    assert row.share == Decimal(5) / Decimal(22)
    assert row.unit_cost == Decimal(18600) / 30  # weighted by quantity: 620 ₽/kg
    assert row.rub == Decimal(3100)


def _row(r: UUID, product: UUID, share: str, theory: str = "500", cost: str = "600") -> m1.M1Row:
    t = Decimal(theory)
    return m1.M1Row(r, product, D0, D1, t, t * (1 + Decimal(share)), Decimal(0), Decimal(cost))


def test_m1_rules_network_pattern_outlier_and_materiality() -> None:
    f, rs, cheese, _ = _facts(restaurants=10)
    norms = Norms()  # «Сыры»: 1.5 %
    # Everyone at ~2 % (normal), R01 at 11 %: only R01 is a problem, measured against the network median.
    rows = [_row(r, cheese, "0.02") for r in rs[1:]] + [_row(rs[0], cheese, "0.11")]
    (d,) = m1.detect(f, rows, norms)
    assert d.key == "M1:R01:P01" and d.restaurant == rs[0]
    # (11 % − 2 %) × 500 kg × 600 ₽ over 60 days → per 30 days
    assert d.effect_rub_month == Decimal(13729)

    # A small kitchen with the same 11 %: under the materiality threshold, not worth a director's time.
    small = [_row(r, cheese, "0.02") for r in rs[1:]] + [_row(rs[0], cheese, "0.11", theory="5")]
    assert m1.detect(f, small, norms) == []

    # Everyone 7–8 % over: the recipe is wrong, not the kitchens — one network finding, no restaurant ones.
    same = [_row(r, cheese, f"0.0{7 + i % 2}") for i, r in enumerate(rs)]
    (net,) = m1.detect(f, same, norms)
    assert net.key == "M1:net:P01" and net.restaurant is None and net.effect_rub_month is None


def test_m1_compares_restaurants_counting_on_their_own_days() -> None:
    """Q15: each restaurant counts stock on its own days; the network is its periods that ended close by."""
    f, rs, cheese, _ = _facts(restaurants=10)

    def shifted(r: UUID, share: str, days: int) -> m1.M1Row:
        t = Decimal(500)
        start, end = D0 + timedelta(days=days), D1 + timedelta(days=days)
        return m1.M1Row(r, cheese, start, end, t, t * (1 + Decimal(share)), Decimal(0), Decimal(600))

    # Nobody shares R01's dates, yet R01 is measured against the other nine (2 %), not alone.
    rows = [shifted(r, "0.02", i + 1) for i, r in enumerate(rs[1:])] + [shifted(rs[0], "0.11", 0)]
    (d,) = m1.detect(f, rows, Norms())
    assert d.key == "M1:R01:P01" and "2,0% в среднем по сети" in d.headline
    assert d.evidence["periods"][-1]["network_share"] == "0.0200"

    # A period that ended too far away is not the same time: with the window at 0 days R01 stands alone,
    # and is judged by the allowance only (no network median in the headline).
    (alone,) = m1.detect(f, rows, Norms(), replace(DEFAULT, M1_NET_ALIGN_DAYS=0))
    assert "в среднем по сети" not in alone.headline


def test_m1_shows_usage_below_the_recipe_as_a_quality_risk() -> None:
    """E3: used noticeably less than the recipes say — no money lost, but guests may get less."""
    f, rs, cheese, _ = _facts(restaurants=10)
    rows = [_row(r, cheese, "0.02") for r in rs[1:]] + [_row(rs[0], cheese, "-0.12")]
    (d,) = m1.detect(f, rows, Norms())
    assert d.key == "M1:R01:P01:under" and d.title == "Расход меньше техкарты: Сыр"
    assert d.effect_rub_month is None and d.evidence["direction"] == "under"
    assert "на 12,0% меньше" in d.headline and "Гости могут получать меньше" in d.headline
    # 12 % × 500 kg × 600 ₽ over 60 days → per 30 days
    assert d.evidence["shortfall_rub_month"] == "18305.00"
    view = views.build(d, f)
    assert view is not None and view["causes"][0] == "На раздаче кладут меньше, чем в техкарте"
    assert view["composition"]["answer"].endswith("на 60 кг меньше.")
    assert view["scale"]["answer"].startswith("Да. Расход относительно техкарты: на 14 пунктов ниже")

    # A few percent less is ordinary noise; a tiny product is not worth attention either.
    assert (
        m1.detect(f, [_row(r, cheese, "0.02") for r in rs[1:]] + [_row(rs[0], cheese, "-0.03")], Norms())
        == []
    )
    small = [_row(r, cheese, "0.02") for r in rs[1:]] + [_row(rs[0], cheese, "-0.12", theory="5")]
    assert m1.detect(f, small, Norms()) == []


def test_m7_dish_without_a_recipe_and_missing_exports() -> None:
    f, rs, cheese, pizza = _facts(restaurants=3)
    soup = uuid4()
    f.menu[soup] = MenuInfo("M12", "Суп", "Супы", Decimal(420))
    end = date(2026, 10, 18)
    days = [end - timedelta(days=i) for i in range(40)]
    f.sales = [SaleRow(r, d, pizza, Decimal(10), Decimal(5800)) for r in rs for d in days]
    f.sales += [SaleRow(rs[0], d, soup, Decimal(2), Decimal(840)) for d in days[:20]]
    # Receipts every other day; R03's stop 8 days before the others' — far longer than its usual pause.
    f.receipts = [
        ReceiptRow(r, d, cheese, None, Decimal(5), Decimal(3000))
        for r in rs
        for d in days[::2]
        if not (r == rs[2] and d > end - timedelta(days=8))
    ]
    drafts = {d.key: d for d in m7.detect(f)}
    assert set(drafts) == {"M7:net:M12", "M7:R03:receipts"}
    no_recipe = drafts["M7:net:M12"]
    assert no_recipe.title == "«Суп» продается без техкарты" and no_recipe.restaurant is None
    # 20 days × 840 ₽ out of the last 28 days' revenue of the network
    assert no_recipe.evidence["revenue_share"] == str(
        (Decimal(20 * 840) / (Decimal(28 * 3 * 5800) + Decimal(20 * 840))).quantize(Decimal("0.0001"))
    )
    gap = drafts["M7:R03:receipts"]
    assert (
        gap.restaurant == rs[2] and gap.evidence["gap_days"] == 8 and gap.evidence["usual_pause_days"] == "2"
    )

    # Once the recipe is loaded, the dish is fine; a pause like the usual one is not a missing export.
    # A recipe loaded a few days ago (code review 27.10.2026): fixed, though the window has sales without it.
    f.recipe_lines.append(Line(soup, cheese, Decimal("0.05"), end - timedelta(days=3)))
    assert "M7:net:M12" not in {d.key for d in m7.detect(f)}
    f.recipe_lines[-1] = Line(soup, cheese, Decimal("0.05"), date(2026, 9, 1))
    f.receipts = [x for x in f.receipts if x.restaurant != rs[2]] + [
        ReceiptRow(rs[2], d, cheese, None, Decimal(5), Decimal(3000)) for d in days[2::2]
    ]
    assert m7.detect(f) == []


def test_m5_write_offs_above_the_network_and_on_the_same_weekdays() -> None:
    f, rs, cheese, pizza = _facts(restaurants=4)
    greens = uuid4()
    f.products[greens] = ProductInfo("P10", "Руккола", "Зелень", "kg", 3, False)
    end = date(2026, 10, 18)  # a Sunday: the window is four whole weeks, Monday to Sunday
    days = [end - timedelta(days=i) for i in range(28)]
    f.sales = [SaleRow(r, d, pizza, Decimal(10), Decimal(5800)) for r in rs for d in days]
    f.receipts = [
        ReceiptRow(r, d, p, None, Decimal(10), Decimal(9000))
        for r in rs
        for d in days[::2]
        for p in (greens, cheese)
    ]
    # Everyone writes off 5 % of the rocket evenly; R01 writes off 25 %.
    for r in rs:
        for d in days[::2]:
            f.write_offs.append(
                WriteOffRow(r, d, greens, Decimal("2.5") if r == rs[0] else Decimal("0.5"), "spoilage")
            )
    # R02 throws away cheese on Mondays and Tuesdays only, every week; R03 — once, before a count.
    for d in days:
        if d.weekday() in (0, 1):
            f.write_offs.append(WriteOffRow(rs[1], d, cheese, Decimal(1), "spoilage"))
    f.write_offs.append(WriteOffRow(rs[2], days[3], cheese, Decimal(4), "spoilage"))
    drafts = {d.key: d for d in m5.detect(f, Usage(f), CostBook(f.receipts))}
    assert set(drafts) == {"M5:R01:P10", "M5:R02:P01"}
    rate = drafts["M5:R01:P10"]
    assert rate.title == "Списания выше сети: Руккола" and rate.evidence["network_rate"] == "0.0500"
    # 35 kg × 900 ₽ written off; above the network: 1 − 5 % / 25 % = 80 % of it, over 28 days → per 30 days
    assert rate.effect_rub_month == Decimal(27000)
    weekdays = drafts["M5:R02:P01"]
    assert weekdays.title == "Списания в понедельник и вторник: Сыр"
    assert weekdays.evidence["weeks_held"] == 4 and weekdays.evidence["share"] == "1.0000"
    view = views.build(weekdays, f)
    assert view is not None and view["table"]["rows"][0][0] == "пн"


def test_m4_write_offs_before_counts_and_mixed_up_products() -> None:
    f, rs, cheese, _ = _facts(restaurants=2)
    grana = uuid4()
    f.products[grana] = ProductInfo("P03", "Грана", "Сыры", "kg", 30, False)
    counts = [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    f.receipts = [
        ReceiptRow(r, date(2026, 6, 15), p, None, Decimal(100), Decimal(60000))
        for r in rs
        for p in (cheese, grana)
    ]
    for r in rs:
        day = counts[0] + timedelta(days=1)
        while day <= counts[-1]:
            # R01 keeps the write-offs for the two days before each count; R02 writes off every day.
            if r == rs[1] or any(1 <= (c - day).days <= 2 for c in counts[1:]):
                f.write_offs.append(
                    WriteOffRow(r, day, cheese, Decimal("0.5") if r == rs[1] else Decimal(5), "spoilage")
                )
            day += timedelta(days=1)
    for r in rs:
        for i, c in enumerate(counts):
            # Both lose about 2 % against the books; at R02's last count the cheeses are mixed up by 1 kg.
            swap = Decimal(1) if (r == rs[1] and i == len(counts) - 1) else Decimal(0)
            f.counts.append(CountRow(r, c, cheese, Decimal(20), Decimal("19.6") + swap if i else Decimal(20)))
            f.counts.append(CountRow(r, c, grana, Decimal(20), Decimal("19.6") - swap if i else Decimal(20)))
    drafts = {d.key: d for d in m4.detect(f, CostBook(f.receipts))}
    assert set(drafts) == {"M4:R01:pre-count", "M4:R02:P01-P03"}
    pre = drafts["M4:R01:pre-count"]
    assert (
        pre.evidence["share"] == "1.0000"
        and pre.title == "100% списаний оформлено за 2 дня до инвентаризации"
    )
    mixed = drafts["M4:R02:P01-P03"]
    assert (
        mixed.title == "Пересорт: сыр и грана" and mixed.evidence["products"]["P01"]["off_usual"] == "1.000"
    )
    assert views.build(mixed, f) is not None and views.build(pre, f) is not None


def test_m6_shortage_before_the_next_delivery() -> None:
    f, rs, cheese, pizza = _facts(restaurants=2)
    end = date(2026, 10, 18)  # Sunday
    days = [end - timedelta(days=i) for i in range(28)]
    # 10 pizzas a day: 1.1 kg of cheese by the recipes; deliveries on Wednesdays.
    f.sales = [SaleRow(r, d, pizza, Decimal(10), Decimal(5800)) for r in rs for d in days]
    f.receipts = [
        ReceiptRow(r, d, cheese, None, Decimal(8), Decimal(4800))
        for r in rs
        for d in days
        if d.weekday() == 2
    ]
    # Counted on Wednesday 14.10 after the delivery: R01 has 6 kg (enough until Sunday only), R02 has 12 kg.
    count = date(2026, 10, 14)
    f.counts = [
        CountRow(rs[0], count, cheese, None, Decimal(6)),
        CountRow(rs[1], count, cheese, None, Decimal(12)),
    ]
    u = Usage(f)
    (d,) = m6.detect(f, u, [])
    assert d.key == "M6:R01:P01:shortage" and d.restaurant == rs[0]
    # 6 kg − 4 days × 1.1 kg = 1.6 kg at the end of Sunday: out on Tuesday 20.10, the delivery on Wednesday.
    assert d.evidence["zero_day"] == "2026-10-20" and d.evidence["next_delivery"] == "2026-10-21"
    assert d.evidence["revenue_per_day"] == "5800"
    assert views.build(d, f) is not None
    # Dishes bringing less than the threshold a day are not worth an alarm.
    assert m6.detect(f, u, [], replace(DEFAULT, M6_REVENUE_AT_RISK=Decimal(10000))) == []


def test_m4_paper_and_overdue_counts_and_m7_books_below_zero() -> None:
    f, rs, cheese, pizza = _facts(restaurants=2)
    counts = [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    end = date(2026, 9, 30)
    f.sales = [
        SaleRow(r, counts[0] + timedelta(days=i), pizza, Decimal(10), Decimal(5800))
        for r in rs
        for i in range(1, (end - counts[0]).days + 1)
    ]
    for r in rs:
        for i, c in enumerate(counts if r == rs[0] else [*counts[:-1], date(2026, 9, 1)]):
            # R01 copies the books on its last two counts; R02 counts honestly, the last time on 01.09.
            paper = r == rs[0] and i >= 2
            actual = Decimal(20) if paper else Decimal("19.5") if r == rs[0] else Decimal(3)
            f.counts.append(CountRow(r, c, cheese, Decimal(20), actual))
    # Weekly deliveries cover the use (1.1 kg a day) — except R02 in August: one invoice is missing.
    for r in rs:
        day = counts[0] + timedelta(days=1)
        while day <= end:
            if day.weekday() == 0 and not (r == rs[1] and day == date(2026, 8, 10)):
                f.receipts.append(ReceiptRow(r, day, cheese, None, Decimal("7.7"), Decimal(4620)))
            day += timedelta(days=1)
    drafts = {d.key: d for d in m4.detect(f, CostBook(f.receipts))}
    assert set(drafts) == {"M4:R01:paper", "M4:R01:overdue"}
    assert drafts["M4:R01:paper"].evidence["counts"] == {"2026-07-01": "1.0000", "2026-08-01": "1.0000"}
    # R01 counts monthly and has not counted for 60 days; R02 counted a month ago.
    assert drafts["M4:R01:overdue"].evidence["since_days"] == 60
    negative = m7.detect_negative_stock(f, Usage(f))
    assert [d.key for d in negative] == ["M7:R02:P01:negative"]
    # 3 kg at the counts, the Monday invoice of 10.08 missing: more than 3 days of use below zero by Tuesday.
    assert negative[0].evidence["first_negative"] == "2026-08-11"
    for d in [*drafts.values(), *negative]:
        assert views.build(d, f) is not None


def _receipts(
    f: Facts, r: UUID, product: UUID, supplier: UUID, price: str, qty: str = "10", n: int = 6
) -> None:
    for i in range(n):
        day = date(2026, 9, 1) + timedelta(days=7 * i)
        f.receipts.append(ReceiptRow(r, day, product, supplier, Decimal(qty), Decimal(qty) * Decimal(price)))


def test_m3_overpay_against_the_network_with_the_supplier_named() -> None:
    f, rs, cheese, _ = _facts(restaurants=4)
    usual, urgent = uuid4(), uuid4()
    f.suppliers = {usual: "Сырный дом", urgent: "Сыр срочно"}
    for r in rs[1:]:
        _receipts(f, r, cheese, usual, "600")
    _receipts(f, rs[0], cheese, urgent, "690", qty="20")  # 15 % more, from another supplier
    (d,) = m3.detect(f)
    assert d.key == "M3:R01:P01" and d.title == "Закупка у дорогого поставщика: Сыр"
    assert "«Сыр срочно»" in d.headline and "«Сырный дом»" in d.headline and "на 15% дороже" in d.headline
    # (690 − 600) × 120 kg = 10 800 ₽ over the 8-week window → per 30 days
    assert d.effect_rub_month == Decimal(5786)

    # The same supplier charging one restaurant more: a different explanation and different actions.
    f.receipts = [r for r in f.receipts if r.restaurant != rs[0]]
    _receipts(f, rs[0], cheese, usual, "690", qty="20")
    (same,) = m3.detect(f)
    assert same.title == "Поставщик продает дороже, чем другим: Сыр" and "единый договор" in " ".join(
        same.actions
    )

    # 3 % more is within the normal spread; a tiny volume is not worth attention.
    f.receipts = [r for r in f.receipts if r.restaurant != rs[0]]
    _receipts(f, rs[0], cheese, usual, "618")
    assert m3.detect(f) == []
    f.receipts = [r for r in f.receipts if r.restaurant != rs[0]]
    _receipts(f, rs[0], cheese, usual, "690", qty="0.5")
    assert m3.detect(f) == []


def test_m2_dish_food_cost_above_target_names_the_cause() -> None:
    f, (r,), cheese, pizza = _facts()
    sup = uuid4()
    # 0.11 kg of cheese per pizza (0.1 directly + 0.05 kg of sauce × 0.2).
    # A quarter ago 600 ₽/kg, now 1 800 ₽/kg.
    _receipts(f, r, cheese, sup, "600", n=4)
    f.receipts = [
        ReceiptRow(x.restaurant, x.day - timedelta(days=91), x.product, x.supplier, x.qty, x.amount)
        for x in f.receipts
    ]
    _receipts(f, r, cheese, sup, "1800", n=4)
    f.sales = [
        SaleRow(r, date(2026, 9, 20) + timedelta(days=i), pizza, Decimal(100), Decimal(58000))
        for i in range(5)
    ]
    (d,) = m2.detect(f, Norms())
    # 0.11 × 1 800 = 198 ₽ per portion / 580 ₽ = 34.1 % against 30 %
    assert d.key == "M2:net:M01" and d.restaurant is None and d.kind == "opportunity"
    assert (
        "34,1% при цели 30%" in d.headline
        and "с 66\u00a0₽ до 198\u00a0₽" in d.headline
        and "сыр: +200%" in d.headline
    )
    assert "В следующем меню цена 660\u00a0₽ вместо 580\u00a0₽" in d.headline  # 198 / 0.30 = 660
    # Free portions (staff meals, 100 % discounts) and no menu price: skipped, not a division by zero.
    free = Facts(**{**f.__dict__, "menu": {pizza: MenuInfo("M01", "Пицца", "Пицца", None)}})
    free.sales = [SaleRow(r, date(2026, 9, 20), pizza, Decimal(10), Decimal(0))]
    assert m2.detect(free, Norms()) == []
    # A pizza target of 35 % (set by HQ for the category): nothing to say.
    assert m2.detect(f, Norms(food_cost_by_category={"Пицца": Decimal(35)})) == []


@pytest.fixture
def demo(network: Network, owner_engine: Engine) -> dict[str, UUID]:
    """The 12-restaurant demo network loaded into tenant A, plus a director for its R01."""
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        load(session, ctx, generate(seed=42), today=date(2026, 10, 19))
        session.commit()
    with Session(owner_engine) as s, s.begin():
        r01 = s.execute(select(Restaurant.id).where(Restaurant.code == "R01")).scalar_one()
        user = User(
            tenant_id=network.a.id, email="r01@a.ru", full_name="R01", password_hash=hash_password(PASSWORD)
        )
        s.add(user)
        s.flush()
        s.add(
            RoleAssignment(
                tenant_id=network.a.id, user_id=user.id, role=Role.RESTAURANT_DIRECTOR, restaurant_id=r01
            )
        )
    return {"R01": r01}


def test_engine_finds_planted_problems_and_review_gates_directors(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 20)
    try:
        hq, analyst, director = (
            login(client, "admin@a.ru"),
            login(client, "analyst@a.ru"),
            login(client, "r01@a.ru"),
        )
        assert client.post("/api/analytics/run", headers=analyst).status_code == 403
        # The button queues a run (202); without a queue it goes right after the response.
        queued = client.post("/api/analytics/run", headers=hq)
        assert queued.status_code == 202 and queued.json()["status"] == "queued"
        latest = client.get("/api/analytics/runs/latest", headers=hq).json()
        assert (latest["status"], latest["trigger"], latest["created"]) == ("done", "manual", 18)
        # Idempotent: the same data gives the same findings, updated in place.
        client.post("/api/analytics/run", headers=hq)
        latest = client.get("/api/analytics/runs/latest", headers=hq).json()
        assert (latest["created"], latest["updated"], latest["removed"]) == (0, 18, 0)

        pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
        by_key = {(f["module"], f["title"]): f for f in pending}
        assert len(pending) == 18 and all(f["review_status"] == "pending" for f in pending)
        assert {t for _, t in by_key} == {
            "Перерасход по техкарте: Сыр Моцарелла",
            "Перерасход по техкарте: Лосось охлажденный",
            "Техкарта, вероятно, устарела: Картофель фри замороженный",
            "Закупка у дорогого поставщика: Говядина вырезка",
            "Поставщик продает дороже, чем другим: Сливки 33%",
            "Фудкост выше целевого: Лосось на гриле",
            "Цена выросла по всей сети: Лосось охлажденный",
            "«Тыквенный суп» продается без техкарты",
            "Закупки из 1С:ERP загружены только по 11.10",
            "59% списаний оформлено за 2 дня до инвентаризации",
            "Пересорт: сыр пармезан и сыр грана падано",
            "Списания выше сети: Руккола",
            "Списания в понедельник и вторник: Хлеб чиабатта",
            "Инвентаризации не было 76 дней",
            "Инвентаризации без расхождений с учетом",
            "Закончится до поставки: Паста спагетти",
            "Расчетный остаток уходит в минус: Сыр Моцарелла",
            "Расход меньше техкарты: Сыр Моцарелла",
        }
        # M4 and M5: the planted habits, each recomputed from the rows by the check.
        for module, title in (
            ("M4", "59% списаний оформлено за 2 дня до инвентаризации"),
            ("M4", "Пересорт: сыр пармезан и сыр грана падано"),
            ("M5", "Списания выше сети: Руккола"),
            ("M5", "Списания в понедельник и вторник: Хлеб чиабатта"),
            ("M4", "Инвентаризации не было 76 дней"),
            ("M4", "Инвентаризации без расхождений с учетом"),
            ("M6", "Закончится до поставки: Паста спагетти"),
            ("M7", "Расчетный остаток уходит в минус: Сыр Моцарелла"),
            ("M1", "Расход меньше техкарты: Сыр Моцарелла"),
        ):
            found = by_key[(module, title)]
            check = client.get(f"/api/findings/{found['id']}/verification", headers=analyst).json()
            assert check["supported"] and all(c["ok"] for c in check["checks"]), check
            assert all(r["passed"] for r in check["rules"]), check
        # M7: both planted data problems, each recomputed from the rows by the check.
        for title in (
            "«Тыквенный суп» продается без техкарты",
            "Закупки из 1С:ERP загружены только по 11.10",
        ):
            m7 = by_key[("M7", title)]
            v7 = client.get(f"/api/findings/{m7['id']}/verification", headers=analyst).json()
            assert v7["supported"] and all(c["ok"] for c in v7["checks"]), v7
            assert all(r["passed"] for r in v7["rules"]), v7
        soup = by_key[("M7", "«Тыквенный суп» продается без техкарты")]
        assert soup["restaurant_id"] is None and soup["headline"].startswith(
            "С 01.09 блюдо продается без техкарты"
        )
        salmon_dish = by_key[("M2", "Фудкост выше целевого: Лосось на гриле")]
        assert salmon_dish["restaurant_id"] is None and "+40% к цене закупки" in salmon_dish["headline"]
        vs = client.get(f"/api/findings/{salmon_dish['id']}/verification", headers=analyst).json()
        assert all(c["ok"] for c in vs["checks"]) and all(r["passed"] for r in vs["rules"])
        beef = by_key[("M3", "Закупка у дорогого поставщика: Говядина вырезка")]
        assert beef["headline"].startswith("С 27.07 говядина вырезка покупают у «Мясной экспресс»")
        vb = client.get(f"/api/findings/{beef['id']}/verification", headers=analyst).json()
        assert all(c["ok"] for c in vb["checks"]) and all(r["passed"] for r in vb["rules"])
        # Not checked yet: not in the working lists or the head report, invisible to the director,
        # and no one can be given a task on it.
        assert client.get("/api/findings", headers=hq).json() == []
        report = client.get("/api/reports/head", headers=hq).json()
        assert Decimal(report["found_rub_month"]) == 0 and report["open_findings_now"] == 0
        task = {"title": "Разобраться", "due_on": "2026-10-27", "finding_id": beef["id"]}
        assert client.post("/api/tasks", headers=hq, json=task).status_code == 422
        assert client.get("/api/findings", headers=director).json() == []
        assert client.get("/api/findings", headers=director, params={"review": "pending"}).status_code == 403

        moz = by_key[("M1", "Перерасход по техкарте: Сыр Моцарелла")]
        v = client.get(f"/api/findings/{moz['id']}/verification", headers=analyst).json()
        assert all(c["ok"] for c in v["checks"]) and all(r["passed"] for r in v["rules"])
        assert [s["id"] for s in v["steps"]] == [
            "opening",
            "receipts",
            "transfers",
            "closing",
            "theory",
            "write_offs",
        ]
        assert any(row["file"] == "receipts_R01.csv" for row in v["steps"][1]["rows"])
        assert client.get(f"/api/findings/{moz['id']}/verification", headers=director).status_code == 403

        url = f"/api/findings/{moz['id']}/review"
        assert client.post(url, headers=analyst, json={"verdict": "reject"}).status_code == 422  # why?
        assert (
            client.post(url, headers=analyst, json={"verdict": "confirm"}).json()["review_status"]
            == "confirmed"
        )
        assert client.post(url, headers=director, json={"verdict": "reopen"}).status_code == 403
        assert [f["id"] for f in client.get("/api/findings", headers=director).json()] == [moz["id"]]
        # The path is traceable: found by the engine → checked by a person → in the working list.
        in_list = next(f for f in client.get("/api/findings", headers=hq).json() if f["id"] == moz["id"])
        assert in_list["module"] == "M1" and in_list["found_on"] == "2026-10-20"
        assert in_list["review_status"] == "confirmed" and in_list["reviewed_on"] == "2026-10-20"
        assert in_list["reviewed_by_name"] == "analyst@a.ru"

        fries = by_key[("M1", "Техкарта, вероятно, устарела: Картофель фри замороженный")]
        # TC-REV-04: the network finding is recomputed restaurant by restaurant from the rows.
        vf = client.get(f"/api/findings/{fries['id']}/verification", headers=analyst).json()
        assert all(c["ok"] for c in vf["checks"]) and all(r["passed"] for r in vf["rules"])
        # R08 skipped its last count: 11 restaurants in the period, 10 of them over the allowance.
        assert len(vf["steps"][0]["rows"]) == 11 and vf["rules"][0]["value"] == "10 из 11"
        rejected = client.post(
            f"/api/findings/{fries['id']}/review",
            headers=hq,
            json={"verdict": "reject", "reason": "false_alarm", "note": "Знаем, техкарту уже меняем"},
        ).json()
        assert rejected["review_status"] == "rejected" and rejected["review_reason"] == "false_alarm"
        # Why HQ rejected or reopened a finding is HQ's note, not the director's.
        client.post(url, headers=analyst, json={"verdict": "reopen", "note": "Сверить с инвентаризацией"})
        client.post(url, headers=analyst, json={"verdict": "confirm", "note": "Сверили"})
        (seen,) = client.get("/api/findings", headers=director).json()
        assert seen["review_note"] is None and seen["reviewed_by_name"] is None
        # A re-run keeps the reviewers' decisions.
        client.post("/api/analytics/run", headers=hq)
        assert {
            f["review_status"]
            for f in client.get("/api/findings", headers=hq, params={"review": "rejected"}).json()
        } == {"rejected"}
        assert [f["id"] for f in client.get("/api/findings", headers=director).json()] == [moz["id"]]

        # New data that changes the amount a lot sends a checked finding back to the check:
        # the director must not see a sum nobody confirmed (here the stored effect plays the old data).
        with Session(owner_engine) as s, s.begin():
            row = s.get(Finding, UUID(moz["id"]))
            assert row is not None
            row.effect_rub_month = Decimal(5000)
        client.post("/api/analytics/run", headers=hq)
        back = next(
            f
            for f in client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
            if f["id"] == moz["id"]
        )
        assert back["review_note"].startswith("Снова на проверке: эффект изменился с 5000")
        assert back["reviewed_on"] is None
        assert client.get("/api/findings", headers=director).json() == []
    finally:
        app.dependency_overrides.pop(get_today, None)


def test_review_can_be_switched_off(client: TestClient, network: Network, demo: dict[str, UUID]) -> None:
    hq = login(client, "admin@a.ru")
    body = client.get("/api/settings/norms", headers=hq).json()
    assert body["review_findings"] is True
    client.put("/api/settings/norms", headers=hq, json={**body, "review_findings": False})
    client.post("/api/analytics/run", headers=hq)
    director = login(client, "r01@a.ru")
    assert {f["title"] for f in client.get("/api/findings", headers=director).json()} == {
        "Перерасход по техкарте: Сыр Моцарелла",
        "Списания выше сети: Руккола",
        "59% списаний оформлено за 2 дня до инвентаризации",
    }


def test_engine_run_is_hq_admin_only(network: Network) -> None:
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["director1@a.ru"], network.a.id)
        assert ctx is not None
        with pytest.raises(Exception, match="администратор"):
            engine.run(session, ctx, date(2026, 10, 20))
        assert session.execute(select(Finding)).scalars().all() == []


def test_m3_contract_prices_and_network_growth() -> None:
    f, rs, cheese, _ = _facts(restaurants=3)
    sup = uuid4()
    f.suppliers = {sup: "Сырный дом"}
    # A quarter ago 600 ₽/kg everywhere, now 700 ₽/kg everywhere: the whole network pays 16.7 % more.
    for r in rs:
        _receipts(f, r, cheese, sup, "600", qty="30", n=4)
    f.receipts = [
        ReceiptRow(x.restaurant, x.day - timedelta(days=91), x.product, x.supplier, x.qty, x.amount)
        for x in f.receipts
    ]
    for r in rs:
        _receipts(f, r, cheese, sup, "700", qty="30", n=4)
    (growth,) = m3.detect_network_growth(f)
    assert growth.key == "M3:net:P01:growth" and growth.restaurant is None
    assert "+17%" in growth.headline and "«Сырный дом»" in growth.headline
    assert m3.detect_contracts(f) == []  # no contract prices loaded

    # With a contract at 600 ₽/kg the same invoices are a breach of contract, not «market growth».
    f.contracts = [ContractRow(sup, cheese, Decimal(600), date(2026, 1, 1), None)]
    assert m3.detect_network_growth(f) == []
    (breach,) = m3.detect_contracts(f)
    assert breach.key == "M3:net:P01:contract" and "при договорной 600" in breach.headline
    # 4 invoices × 30 kg × 100 ₽ over the contract in each restaurant
    assert breach.evidence["restaurants"] == {"R01": "12000.00", "R02": "12000.00", "R03": "12000.00"}


def test_engine_params_are_set_per_network_and_change_the_findings(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    params = {p["key"]: p for p in client.get("/api/settings/engine", headers=director).json()}
    # Shown in the units people use: 75 %, 3 000 ₽, 0,5 п.п.
    assert params["M1_NET_SHARE"]["value"] == "75" and params["M1_MATERIALITY_RUB_MONTH"]["value"] == "3000"
    assert params["M1_Z_FLOOR"]["value"] == "0.5" and params["M1_Z_FLOOR"]["unit"] == "п.п."
    assert (
        client.put("/api/settings/engine", headers=director, json={"values": {"M1_Z": 3}}).status_code == 403
    )
    assert client.put("/api/settings/engine", headers=hq, json={"values": {"M1_Z": 9}}).status_code == 422
    assert client.put("/api/settings/engine", headers=hq, json={"values": {"NOPE": 1}}).status_code == 422

    def keys() -> set[str]:
        return {
            f["module"] + ":" + f["title"]
            for f in client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
        }

    client.post("/api/analytics/run", headers=hq)
    assert "M3:Поставщик продает дороже, чем другим: Сливки 33%" in keys()
    # Overpaying is a finding only above 20 % now: the 14 % cream disappears, the 40 % salmon growth stays.
    saved = client.put("/api/settings/engine", headers=hq, json={"values": {"M3_OVERPAY": 20}}).json()
    assert {p["key"]: p["value"] for p in saved}["M3_OVERPAY"] == "20"
    client.post("/api/analytics/run", headers=hq)
    assert "M3:Поставщик продает дороже, чем другим: Сливки 33%" not in keys()
    assert "M3:Цена выросла по всей сети: Лосось охлажденный" in keys()
    # Another network keeps the defaults; None returns a parameter to its default.
    other = {
        p["key"]: p["value"]
        for p in client.get("/api/settings/engine", headers=login(client, "admin@b.ru")).json()
    }
    assert other["M3_OVERPAY"] == "5"
    back = client.put("/api/settings/engine", headers=hq, json={"values": {"M3_OVERPAY": None}}).json()
    assert {p["key"]: p["value"] for p in back}["M3_OVERPAY"] == "5"


def test_check_of_a_pre_count_finding_after_the_counts_were_rolled_back(network: Network) -> None:
    """Code review 27.10.2026: fewer than two counts left must not crash the check (500)."""
    from app.analytics.verify import verify

    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        f = Finding(
            tenant_id=network.a.id,
            restaurant_id=network.a.restaurants["A1"],
            key="M4:A1:pre-count",
            module="M4",
            kind="problem",
            process="inventory",
            title="t",
            headline="h",
            status="new",
            found_on=date(2026, 10, 20),
            evidence={"kind": "pre_count", "days_before": 2, "share": "0.6", "counts": []},
        )
        session.add(f)
        session.flush()
        result = verify(session, f)
        assert result["supported"] is False and "меньше двух" in result["note"]
