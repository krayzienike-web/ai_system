"""Import through the API: roles, isolation, report, idempotent publish, rollback, demo network load."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.period import get_today
from app.demo.generator import generate
from app.demo.loader import load
from app.main import app
from app.operations.models import Sale
from app.tenancy.context import load_access_context
from tests.conftest import Network, login

TODAY = date(2026, 10, 25)
PRODUCTS = "Код;Наименование;Базовая ед.\nP1;Сыр Моцарелла;кг\nP2;Сливки 33%;л\n"
MENU = "Код;Блюдо;Цена\nM1;Маргарита;580\n"
SALES = "Дата;Блюдо;Кол-во;Сумма\n01.10.2026;Маргарита;3;1740\n02.10.2026;Маргарита;2;1160\n"


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def upload(
    client: TestClient,
    headers: dict[str, str],
    template: str,
    content: str,
    restaurant: object = None,
    name: str = "f.csv",
) -> httpx.Response:
    data = {"template": template}
    if restaurant is not None:
        data["restaurant_id"] = str(restaurant)
    response: httpx.Response = client.post(
        "/api/imports", headers=headers, data=data, files={"file": (name, content.encode(), "text/csv")}
    )
    return response


def publish(client: TestClient, headers: dict[str, str], batch_id: str) -> dict[str, Any]:
    r = client.post(f"/api/imports/{batch_id}/publish", headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


@pytest.fixture
def catalog(client: TestClient, network: Network) -> None:
    hq = login(client, "admin@a.ru")
    for template, content in (("products", PRODUCTS), ("menu_items", MENU)):
        publish(client, hq, upload(client, hq, template, content).json()["id"])


def _sales_count(owner_engine: Engine) -> int:
    with owner_engine.connect() as c:
        return int(c.execute(text("SELECT count(*) FROM sales")).scalar_one())


def test_director_uploads_own_restaurant_and_sees_only_own_batches(
    client: TestClient, network: Network, catalog: None
) -> None:
    director = login(client, "director1@a.ru")
    r = upload(client, director, "sales", SALES, network.a.restaurants["A1"])
    assert r.status_code == 201 and r.json()["status"] == "validated"
    assert (r.json()["period_from"], r.json()["period_to"], r.json()["rows_valid"]) == (
        "2026-10-01",
        "2026-10-02",
        2,
    )
    # Another restaurant of the network or of another tenant: invisible.
    assert upload(client, director, "sales", SALES + "\n", network.a.restaurants["A2"]).status_code == 404
    assert upload(client, director, "sales", SALES + " ", network.b.restaurants["B1"]).status_code == 404
    assert [b["template"] for b in client.get("/api/imports", headers=director).json()] == ["sales"]
    other = login(client, "director2@a.ru")
    assert client.get("/api/imports", headers=other).json() == []
    assert client.get(f"/api/imports/{r.json()['id']}", headers=other).status_code == 404
    assert client.post(f"/api/imports/{r.json()['id']}/publish", headers=other).status_code == 404
    assert client.get("/api/imports", headers=login(client, "admin@b.ru")).json() == []


def test_reference_data_is_hq_only(client: TestClient, network: Network) -> None:
    assert upload(client, login(client, "director1@a.ru"), "products", PRODUCTS).status_code == 403
    assert upload(client, login(client, "analyst@a.ru"), "products", PRODUCTS).status_code == 403
    assert (
        upload(
            client, login(client, "admin@a.ru"), "products", PRODUCTS, network.a.restaurants["A1"]
        ).status_code
        == 422
    )


def test_report_lists_errors_by_row_and_failed_file_cannot_be_published(
    client: TestClient, network: Network, catalog: None
) -> None:
    hq = login(client, "admin@a.ru")
    bad = (
        "Дата;Блюдо;Кол-во;Сумма\n"
        "01.10.2026;Маргарита;3;1740\n"
        "02.10.2026;Пицца Х;2;1160\n"
        "31.10.2026;Маргарита;1;580\n"
    )
    r = upload(client, hq, "sales", bad, network.a.restaurants["A1"]).json()
    assert r["status"] == "failed"
    assert [(e["row"], e["column"]) for e in r["errors"]] == [(4, "Дата")]
    assert [(u["name"], u["rows"]) for u in r["unmatched"]] == [("Пицца Х", [3])]
    assert client.post(f"/api/imports/{r['id']}/publish", headers=hq).status_code == 422
    no_header = upload(client, hq, "sales", "a;b\n1;2\n", network.a.restaurants["A1"]).json()
    assert (
        no_header["status"] == "failed" and "Не нашли строку заголовков" in no_header["errors"][0]["message"]
    )


def test_publish_replaces_the_period_and_duplicate_files_are_refused(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    first = upload(client, hq, "sales", SALES, a1).json()
    publish(client, hq, first["id"])
    assert _sales_count(owner_engine) == 2
    assert upload(client, hq, "sales", SALES, a1).status_code == 409
    # A corrected export of the same days replaces them instead of adding.
    corrected = SALES.replace(";3;1740", ";4;2320")
    publish(client, hq, upload(client, hq, "sales", corrected, a1).json()["id"])
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT sum(qty) FROM sales")).scalar_one() == 6
    # Another restaurant's data for the same days is untouched.
    publish(client, hq, upload(client, hq, "sales", SALES + "\n", network.a.restaurants["A2"]).json()["id"])
    assert _sales_count(owner_engine) == 4


def test_rollback_removes_exactly_the_batch(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    director = login(client, "director1@a.ru")
    batch = upload(client, director, "sales", SALES, network.a.restaurants["A1"]).json()
    publish(client, director, batch["id"])
    r = client.post(f"/api/imports/{batch['id']}/rollback", headers=director)
    assert r.json()["status"] == "rolled_back"
    assert _sales_count(owner_engine) == 0
    assert client.post(f"/api/imports/{batch['id']}/rollback", headers=director).status_code == 422


def test_templates_are_described_for_the_ui(client: TestClient, network: Network) -> None:
    templates = {
        t["name"]: t
        for t in client.get("/api/imports/templates", headers=login(client, "director1@a.ru")).json()
    }
    assert templates["sales"]["one_of"] == [["Код блюда", "Блюдо"]]
    assert {"title": "Количество", "required": True} | {
        "synonyms": ["кол-во", "кол-во блюд", "количество блюд"]
    } in templates["sales"]["columns"]


def test_demo_network_loads_through_the_pipeline_with_rls(network: Network, owner_engine: Engine) -> None:
    from app.core.db import get_sessionmaker

    net = generate(seed=1, restaurants=4)  # R04 has 1С names: the loader matches them once
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        rows = load(session, ctx, net, today=TODAY)
        session.commit()
    assert rows["restaurants"] == 4 and rows["products"] == 16 and rows["sales"] > 7000
    with Session(owner_engine) as s:
        # The generator's R01–R04 are new restaurants of tenant A next to A1–A3.
        codes = (
            s.execute(
                text("SELECT code FROM restaurants WHERE tenant_id = :t ORDER BY code"), {"t": network.a.id}
            )
            .scalars()
            .all()
        )
        assert codes == ["A1", "A2", "A3", "R01", "R02", "R03", "R04"]
        aliases = s.execute(
            text("SELECT count(*) FROM name_aliases WHERE restaurant_id IS NULL")
        ).scalar_one()
        assert aliases == len(net.name_matches) == 5
        assert s.execute(select(func.count()).select_from(Sale)).scalar_one() == rows["sales"]


def test_file_type_is_recognised_without_a_template(
    client: TestClient, network: Network, catalog: None
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    sales = client.post(
        "/api/imports", headers=hq, data={"restaurant_id": str(a1)}, files={"file": ("x.csv", SALES.encode())}
    ).json()
    assert sales["template"] == "sales"
    counts = "Дата;Товар;Учетный остаток;Фактический остаток\n01.10.2026;Сыр Моцарелла;45;43\n"
    r = client.post(
        "/api/imports",
        headers=hq,
        data={"restaurant_id": str(a1)},
        files={"file": ("y.csv", counts.encode())},
    )
    assert r.json()["template"] == "inventory_counts"
    # Without a restaurant only reference data is considered.
    suppliers = "Код;Название;ИНН\nS1;Сырный дом;7701234567\n"
    assert (
        client.post("/api/imports", headers=hq, files={"file": ("z.csv", suppliers.encode())}).json()[
            "template"
        ]
        == "suppliers"
    )
    unknown = client.post(
        "/api/imports", headers=hq, data={"restaurant_id": str(a1)}, files={"file": ("w.csv", b"a;b\n1;2\n")}
    )
    assert unknown.status_code == 422 and "Не узнали файл" in unknown.json()["detail"]


def test_freshness_per_restaurant_and_isolation(client: TestClient, network: Network, catalog: None) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    publish(client, hq, upload(client, hq, "sales", SALES, a1).json()["id"])
    rows = client.get("/api/imports/freshness", headers=hq).json()
    assert len(rows) == 3 * 4
    a1_sales = next(r for r in rows if r["restaurant_id"] == str(a1) and r["template"] == "sales")
    # Data up to 02.10, nothing in the last full week 12–18.10: stale.
    assert (a1_sales["last_date"], a1_sales["status"]) == ("2026-10-02", "stale")
    assert {r["status"] for r in rows if r["restaurant_id"] != str(a1)} == {"missing"}
    director = client.get("/api/imports/freshness", headers=login(client, "director2@a.ru")).json()
    assert {r["restaurant_id"] for r in director} == {str(network.a.restaurants["A2"])}
    assert (
        client.get("/api/imports/freshness", headers=login(client, "admin@b.ru")).json()[0]["status"]
        == "missing"
    )


RECEIPTS_1C = (
    "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n"
    "01.10.2026;Моцарелла фиор ди латте 45%;5;кг;3100\n"
    "02.10.2026;Моцарелла фиор ди латте 45%;3;кг;1860\n"
    "02.10.2026;Сливки 33% (Молочный двор);2;л;720\n"
)


def test_unknown_names_are_matched_once_and_remembered(
    client: TestClient, network: Network, catalog: None
) -> None:
    director, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    batch = upload(client, director, "receipts", RECEIPTS_1C, a1).json()
    assert batch["status"] == "needs_matching" and batch["errors"] == []
    mozz = next(u for u in batch["unmatched"] if u["name"].startswith("Моцарелла"))
    assert mozz["rows"] == [2, 3] and mozz["kind"] == "product"
    assert mozz["candidates"][0]["name"] == "Сыр Моцарелла"
    assert client.post(f"/api/imports/{batch['id']}/publish", headers=director).status_code == 422

    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=director).json()}
    matches = [
        {
            "kind": "product",
            "key": u["key"],
            "target_id": options["Сыр Моцарелла" if "Моцарелла" in u["name"] else "Сливки 33%"],
        }
        for u in batch["unmatched"]
    ]
    matched = client.post(
        f"/api/imports/{batch['id']}/match", headers=director, json={"matches": matches}
    ).json()
    assert matched["status"] == "validated" and matched["unmatched"] == [] and matched["rows_valid"] == 3
    publish(client, director, batch["id"])

    # Remembered for this restaurant: the next export of A1 goes through at once…
    again = upload(client, director, "receipts", RECEIPTS_1C.replace("01.10", "03.10"), a1).json()
    assert again["status"] == "validated"
    # …but a director's choice does not change another restaurant's numbers.
    other = upload(
        client, login(client, "director2@a.ru"), "receipts", RECEIPTS_1C, network.a.restaurants["A2"]
    ).json()
    assert other["status"] == "needs_matching"


def test_hq_admin_match_applies_to_the_whole_network(
    client: TestClient, network: Network, catalog: None
) -> None:
    hq = login(client, "admin@a.ru")
    batch = upload(client, hq, "receipts", RECEIPTS_1C, network.a.restaurants["A1"]).json()
    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=hq).json()}
    matches = [
        {
            "kind": "product",
            "key": u["key"],
            "target_id": options["Сыр Моцарелла" if "Моцарелла" in u["name"] else "Сливки 33%"],
        }
        for u in batch["unmatched"]
    ]
    assert (
        client.post(f"/api/imports/{batch['id']}/match", headers=hq, json={"matches": matches}).json()[
            "status"
        ]
        == "validated"
    )
    other = upload(
        client, login(client, "director2@a.ru"), "receipts", RECEIPTS_1C, network.a.restaurants["A2"]
    ).json()
    assert other["status"] == "validated"


def test_matching_rules_and_isolation(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    director, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    batch = upload(client, director, "receipts", RECEIPTS_1C, a1).json()
    key = batch["unmatched"][0]["key"]
    menu = client.get("/api/catalog/menu_item", headers=director).json()
    # A key that is not in the report, or a target of another kind, is refused.
    bad_key = {"matches": [{"kind": "product", "key": "что-то еще", "target_id": menu[0]["id"]}]}
    assert client.post(f"/api/imports/{batch['id']}/match", headers=director, json=bad_key).status_code == 422
    wrong_kind = {"matches": [{"kind": "product", "key": key, "target_id": menu[0]["id"]}]}
    assert (
        client.post(f"/api/imports/{batch['id']}/match", headers=director, json=wrong_kind).status_code == 404
    )
    # Another director or another tenant cannot touch the batch; another tenant's catalog is invisible.
    body = {"matches": [{"kind": "product", "key": key, "target_id": menu[0]["id"]}]}
    assert (
        client.post(
            f"/api/imports/{batch['id']}/match", headers=login(client, "director2@a.ru"), json=body
        ).status_code
        == 404
    )
    assert client.get("/api/catalog/product", headers=login(client, "admin@b.ru")).json() == []
    # In the database, a director cannot write a network-wide match (row-level security).
    with owner_engine.connect() as c:
        policy = c.execute(
            text("SELECT with_check FROM pg_policies WHERE tablename = 'name_aliases'")
        ).scalar_one()
    assert "restaurant_id IS NOT NULL" in policy
