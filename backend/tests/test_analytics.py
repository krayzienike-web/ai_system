"""Analytics engine: M1 arithmetic, decision rules, a full run on the demo network, manual review."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.analytics import engine, m1, m2, m3
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
    assert "Цена 660\u00a0₽ вместо 580\u00a0₽" in d.headline  # 198 / 0.30 = 660
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
        run = client.post("/api/analytics/run", headers=hq).json()
        assert run["created"] == 7
        # Idempotent: the same data gives the same findings, updated in place.
        assert client.post("/api/analytics/run", headers=hq).json() | {} == {
            "created": 0,
            "updated": 7,
            "removed": 0,
            "drafts": 7,
        }

        pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
        by_key = {(f["module"], f["title"]): f for f in pending}
        assert len(pending) == 7 and all(f["review_status"] == "pending" for f in pending)
        assert {t for _, t in by_key} == {
            "Перерасход по техкарте: Сыр Моцарелла",
            "Перерасход по техкарте: Лосось охлажденный",
            "Техкарта, вероятно, устарела: Картофель фри замороженный",
            "Закупка у дорогого поставщика: Говядина вырезка",
            "Поставщик продает дороже, чем другим: Сливки 33%",
            "Фудкост выше целевого: Лосось на гриле",
            "Цена выросла по всей сети: Лосось охлажденный",
        }
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
    assert [f["title"] for f in client.get("/api/findings", headers=director).json()] == [
        "Перерасход по техкарте: Сыр Моцарелла"
    ]


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
