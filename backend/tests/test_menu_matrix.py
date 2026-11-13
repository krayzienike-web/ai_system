"""Menu engineering (docs/12 «Меню-инжиниринг»): popularity × margin by category — the four quadrants, the
window, one restaurant's popularity, what is not counted; the HQ's report only."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.analytics import menu
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow
from app.catalog.models import MenuItem, Product, RecipeLine
from app.catalog.recipes import Line
from app.imports.models import ImportBatch
from app.operations.models import Receipt, Sale
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


def test_the_edges_of_a_category_and_what_is_not_counted() -> None:
    """TC-AN-62: a dish exactly at «popular from» (0,35 of two) and exactly at the average margin is a star;
    the cost through a semi-product; a dish without a category is under «Без категории», alone in it — a star;
    no price, a zero price or an ingredient without a purchase — not counted; sales after the latest invoice
    are out of the window."""
    cheese, basil, sauce = uuid4(), uuid4(), uuid4()
    x, y, z, no_price, zero, no_basil = (uuid4() for _ in range(6))
    facts = Facts(
        products={
            cheese: ProductInfo("P1", "Сыр", None, "kg", None, False),
            basil: ProductInfo("P2", "Базилик", None, "kg", None, False),
            sauce: ProductInfo("S1", "Соус", None, "kg", None, True),
        },
        menu={
            x: MenuInfo("X", "Маргарита", "Пицца", Decimal(110)),
            y: MenuInfo("Y", "Пицца с соусом", "Пицца", Decimal(110)),
            z: MenuInfo("Z", "Морс", None, Decimal(50)),
            no_price: MenuInfo("W", "Без цены", "Пицца", None),
            zero: MenuInfo("V", "Цена ноль", "Пицца", Decimal(0)),
            no_basil: MenuInfo("U", "Базилик без закупок", "Пицца", Decimal(100)),
        },
        recipe_lines=[
            Line(x, cheese, Decimal("0.1"), date(2026, 1, 1)),  # 0,1 kg × 100 ₽ = 10 ₽
            Line(y, sauce, Decimal("0.2"), date(2026, 1, 1)),  # 0,2 kg of the sauce …
            Line(sauce, cheese, Decimal("0.5"), date(2026, 1, 1)),  # … × 0,5 kg of cheese = 0,1 kg: 10 ₽
            Line(z, cheese, Decimal("0.1"), date(2026, 1, 1)),
            Line(no_price, cheese, Decimal("0.1"), date(2026, 1, 1)),
            Line(zero, cheese, Decimal("0.1"), date(2026, 1, 1)),
            Line(no_basil, basil, Decimal("0.01"), date(2026, 1, 1)),
        ],
        sales=[
            SaleRow(R1, END, x, Decimal(65), Decimal(0)),
            SaleRow(R1, END, y, Decimal(35), Decimal(0)),
            SaleRow(R1, END + timedelta(days=1), y, Decimal(1000), Decimal(0)),  # after the latest invoice
            SaleRow(R1, END, z, Decimal(5), Decimal(0)),
            *(SaleRow(R1, END, i, Decimal(10), Decimal(0)) for i in (no_price, zero, no_basil)),
        ],
        receipts=[ReceiptRow(R1, END, cheese, None, Decimal(10), Decimal(1000))],
    )
    m = menu.matrix(facts)
    assert [c.name for c in m.categories] == ["Без категории", "Пицца"]
    alone, pizza = m.categories
    assert [(d.name, d.share, d.quadrant) for d in alone.dishes] == [("Морс", Decimal("1.0000"), "star")]
    assert (alone.margin, alone.fair_share, alone.popular_from) == (
        Decimal("40.00"),  # 50 − 10
        Decimal("1.0000"),
        Decimal("0.7000"),
    )
    # 1/2 × 0,7 = 0,35; the average (100 × 65 + 100 × 35) / 100 = 100 ₽ — both at the edge, both stars.
    assert (pizza.margin, pizza.popular_from) == (Decimal("100.00"), Decimal("0.3500"))
    assert [(d.name, d.share, d.cost, d.margin, d.quadrant) for d in pizza.dishes] == [
        ("Маргарита", Decimal("0.6500"), Decimal("10.00"), Decimal("100.00"), "star"),
        ("Пицца с соусом", Decimal("0.3500"), Decimal("10.00"), Decimal("100.00"), "star"),
    ]
    assert pizza.dishes[1].portions_month == Decimal("37.5")  # 35 × 30 / 28
    assert m.not_counted == ["Базилик без закупок", "Без цены", "Цена ноль"]


def _dish(s: Session, tenant: UUID, restaurant: UUID, code: str, name: str, portions: int, day: date) -> None:
    """A dish of the tenant at 300 ₽ with 0,2 kg of cheese bought at 500 ₽/kg (cost 100 ₽), `portions`
    sold."""
    batch = ImportBatch(
        tenant_id=tenant,
        restaurant_id=restaurant,
        template="receipts",
        filename=f"{code}.csv",
        sha256=uuid4().hex * 2,
        raw=b"",
        status="published",
    )
    cheese = Product(tenant_id=tenant, code=f"P-{code}", name="Сыр", base_unit="kg")
    item = MenuItem(tenant_id=tenant, code=code, name=name, category="Пицца", price=Decimal(300))
    s.add_all([batch, cheese, item])
    s.flush()
    s.add_all(
        [
            RecipeLine(
                tenant_id=tenant,
                menu_item_id=item.id,
                product_id=cheese.id,
                gross_qty=Decimal("0.2"),
                valid_from=date(2026, 1, 1),
            ),
            Receipt(
                tenant_id=tenant,
                restaurant_id=restaurant,
                import_batch_id=batch.id,
                day=day,
                doc_no="",
                supplier_id=None,
                product_id=cheese.id,
                qty=Decimal(10),
                amount=Decimal(5000),
            ),
            Sale(
                tenant_id=tenant,
                restaurant_id=restaurant,
                import_batch_id=batch.id,
                day=day,
                menu_item_id=item.id,
                qty=Decimal(portions),
                revenue=Decimal(300 * portions),
            ),
        ]
    )


def test_the_menu_report_reads_only_its_networks_data(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AN-63 (CLAUDE.md, p. 2): with data in both networks the HQ of A sees A's dishes, its prices and its
    window only — not B's dish nor B's later invoice; the HQ of B sees B's; one restaurant's sales."""
    a, b = network.a, network.b
    with Session(owner_engine) as s, s.begin():
        _dish(s, a.id, a.restaurants["A1"], "M1", "Маргарита", 28, END)
        _dish(s, b.id, b.restaurants["B1"], "M9", "Чужая пицца", 56, END + timedelta(days=5))
    r = client.get("/api/reports/menu", headers=login(client, "admin@a.ru"))
    assert r.status_code == 200, r.text
    body = r.json()
    # A's latest invoice 18.10 (B's 23.10 is not A's): 28 days back from it.
    assert (body["since"], body["until"]) == ("2026-09-21", "2026-10-18")
    (pizza,) = body["categories"]
    (dish,) = pizza["dishes"]
    # 300 − 0,2 × 500 = 200 ₽ a portion; 28 portions × 30 / 28 = 30 a month.
    assert (dish["name"], dish["cost"], dish["margin"], dish["food_cost"], dish["portions_month"]) == (
        "Маргарита",
        "100.00",
        "200.00",
        "0.3333",
        "30.0",
    )
    assert body["not_counted"] == []
    other = client.get("/api/reports/menu", headers=login(client, "admin@b.ru")).json()
    assert [d["name"] for c in other["categories"] for d in c["dishes"]] == ["Чужая пицца"]
    a2 = client.get(
        f"/api/reports/menu?restaurant_id={a.restaurants['A2']}", headers=login(client, "admin@a.ru")
    ).json()
    assert a2["categories"] == [] and a2["not_counted"] == ["Маргарита"]  # A2 sold none of it
