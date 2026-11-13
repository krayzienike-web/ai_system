"""Menu engineering (docs/12 «Меню-инжиниринг»): popularity × margin by category — the four quadrants, the
window, one restaurant's popularity, what is not counted; the HQ's report only."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.analytics import menu
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow
from app.catalog.recipes import Line
from tests.conftest import Network, login

END = date(2026, 10, 18)
R1, R2 = uuid4(), uuid4()


def _facts() -> Facts:
    cheese = uuid4()
    a, b, c, d, no_card, no_sale = (uuid4() for _ in range(6))
    menu_items = {
        a: MenuInfo("A", "Звезда", "Пицца", Decimal(110)),
        b: MenuInfo("B", "Лошадка", "Пицца", Decimal(60)),
        c: MenuInfo("C", "Загадка", "Пицца", Decimal(210)),
        d: MenuInfo("D", "Собака", "Пицца", Decimal(40)),
        no_card: MenuInfo("E", "Без техкарты", "Пицца", Decimal(100)),
        no_sale: MenuInfo("F", "Без продаж", "Пицца", Decimal(100)),
    }
    lines = [Line(i, cheese, Decimal("0.1"), date(2026, 1, 1)) for i in (a, b, c, d, no_sale)]
    sales = [
        SaleRow(R1, END, a, Decimal(40), Decimal(0)),
        SaleRow(R1, END, b, Decimal(40), Decimal(0)),
        SaleRow(R1, END - timedelta(days=27), c, Decimal(10), Decimal(0)),  # the window's first day
        SaleRow(R2, END, d, Decimal(10), Decimal(0)),
        SaleRow(R1, END - timedelta(days=28), d, Decimal(500), Decimal(0)),  # before the window
    ]
    return Facts(
        products={cheese: ProductInfo("P1", "Сыр", "Сыры", "kg", 10, False)},
        menu=menu_items,
        recipe_lines=lines,
        sales=sales,
        receipts=[ReceiptRow(R1, END, cheese, None, Decimal(10), Decimal(1000))],  # 100 ₽/kg: 10 ₽ a portion
    )


def test_the_four_quadrants_of_a_category() -> None:
    """TC-AN-60: popular — from 70 % of an equal share (0,175 of four); high margin — at or above the
    category's weighted average, 83 ₽; a month is 30 days of the 28-day window."""
    m = menu.matrix(_facts())
    assert (m.since, m.until) == (date(2026, 9, 21), END)
    (pizza,) = m.categories
    assert (pizza.name, pizza.margin, pizza.fair_share, pizza.popular_from) == (
        "Пицца",
        Decimal("83.00"),
        Decimal("0.2500"),
        Decimal("0.1750"),
    )
    assert [(x.name, x.quadrant, x.margin, x.share) for x in pizza.dishes] == [
        ("Звезда", "star", Decimal("100.00"), Decimal("0.4000")),
        ("Лошадка", "plowhorse", Decimal("50.00"), Decimal("0.4000")),
        ("Загадка", "puzzle", Decimal("200.00"), Decimal("0.1000")),
        ("Собака", "dog", Decimal("30.00"), Decimal("0.1000")),
    ]
    star = pizza.dishes[0]
    assert (star.cost, star.food_cost, star.portions_month) == (
        Decimal("10.00"),
        Decimal("0.0909"),
        Decimal("42.9"),
    )
    assert m.not_counted == ["Без продаж", "Без техкарты"]


def test_one_restaurants_popularity_and_no_data() -> None:
    """TC-AN-60: popularity of one restaurant with the network's prices; no invoices — an empty matrix."""
    m = menu.matrix(_facts(), restaurant=R2)
    (pizza,) = m.categories
    assert [(x.name, x.share) for x in pizza.dishes] == [("Собака", Decimal("1.0000"))]
    assert pizza.dishes[0].quadrant == "star"  # alone in its category: as popular and as good as itself
    assert menu.matrix(Facts()) == menu.Matrix(None, None)


def test_the_menu_report_is_the_hqs(client: TestClient, network: Network) -> None:
    """TC-AN-61 (CLAUDE.md, p. 2): the HQ gets the report; a director does not (403); a restaurant of another
    network is not found (404)."""
    hq = login(client, "admin@a.ru")
    r = client.get("/api/reports/menu", headers=hq)
    assert r.status_code == 200, r.text
    assert r.json()["categories"] == [] and r.json()["restaurant_id"] is None
    assert (r.json()["popularity"], r.json()["window_days"]) == ("0.7", 28)  # the engine's, not the screen's
    mine = network.a.restaurants["A1"]
    assert client.get(f"/api/reports/menu?restaurant_id={mine}", headers=hq).status_code == 200
    other = network.b.restaurants["B1"]
    assert client.get(f"/api/reports/menu?restaurant_id={other}", headers=hq).status_code == 404
    director = login(client, "director1@a.ru")
    assert client.get("/api/reports/menu", headers=director).status_code == 403
