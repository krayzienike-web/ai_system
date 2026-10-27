"""Import through the API: roles, isolation, report, idempotent publish, rollback, demo network load."""

import threading
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.errors import InvalidError
from app.core.period import get_today
from app.demo.generator import generate
from app.demo.loader import load
from app.imports import service
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


def _sales_by_day(owner_engine: Engine) -> dict[str, int]:
    with owner_engine.connect() as c:
        rows = c.execute(text("SELECT day, sum(qty) FROM sales GROUP BY day ORDER BY day")).all()
    return {d.strftime("%d.%m"): int(q) for d, q in rows}


def _sales(*days: tuple[str, int]) -> str:
    return "Дата;Блюдо;Кол-во;Сумма\n" + "".join(f"{d}.10.2026;Маргарита;{q};{q * 580}\n" for d, q in days)


def test_overlapping_files_later_replaces_and_rollback_restores(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    """TC-IMP-11: a later file replaces the days it covers; rolling it back brings the earlier file's days
    back instead of leaving a hole; re-processing the earlier file does not overwrite the later one."""
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    early = upload(client, hq, "sales", _sales(("01", 1), ("02", 1), ("03", 1), ("04", 1)), a1).json()
    publish(client, hq, early["id"])
    late = upload(client, hq, "sales", _sales(("03", 5), ("04", 5), ("05", 5), ("06", 5)), a1).json()
    publish(client, hq, late["id"])
    after_both = {"01.10": 1, "02.10": 1, "03.10": 5, "04.10": 5, "05.10": 5, "06.10": 5}
    assert _sales_by_day(owner_engine) == after_both

    # Re-processing the earlier file keeps the later file's days.
    assert client.post(f"/api/imports/{early['id']}/reprocess", headers=hq).status_code == 200
    assert _sales_by_day(owner_engine) == after_both

    # Rolling the later file back: the earlier file's 03–04.10 come back, 05–06.10 are gone.
    assert client.post(f"/api/imports/{late['id']}/rollback", headers=hq).status_code == 200
    assert _sales_by_day(owner_engine) == {"01.10": 1, "02.10": 1, "03.10": 1, "04.10": 1}

    # Rolling back the earlier one too leaves nothing.
    assert client.post(f"/api/imports/{early['id']}/rollback", headers=hq).status_code == 200
    assert _sales_by_day(owner_engine) == {}


def test_rolling_back_an_earlier_file_keeps_what_a_later_one_replaced(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    early = upload(client, hq, "sales", _sales(("01", 1), ("02", 1), ("03", 1)), a1).json()
    publish(client, hq, early["id"])
    late = upload(client, hq, "sales", _sales(("02", 5), ("03", 5)), a1).json()
    publish(client, hq, late["id"])
    assert client.post(f"/api/imports/{early['id']}/rollback", headers=hq).status_code == 200
    assert _sales_by_day(owner_engine) == {"02.10": 5, "03.10": 5}


def test_publishing_twice_at_once_writes_the_rows_once(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    """TC-IMP-12: two «Опубликовать» at the same moment: the second waits for the first and is refused."""
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    batch = upload(client, hq, "sales", SALES, a1).json()
    admin = network.a.users["admin@a.ru"]
    results: list[str] = []
    started = threading.Barrier(2)

    def press() -> None:
        with get_sessionmaker()() as session:
            ctx = load_access_context(session, admin, network.a.id)
            assert ctx is not None
            started.wait()
            try:
                service.publish(session, ctx, UUID(batch["id"]), today=TODAY)
                session.commit()
                results.append("published")
            except InvalidError:
                session.rollback()
                results.append("refused")

    threads = [threading.Thread(target=press) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == ["published", "refused"]
    assert _sales_count(owner_engine) == 2


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
    assert rows["restaurants"] == 4 and rows["products"] == 17 and rows["sales"] > 7000
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
            text("SELECT with_check FROM pg_policies WHERE policyname = 'name_aliases_insert'")
        ).scalar_one()
    assert "restaurant_id IS NOT NULL" in policy


def _match_all(
    client: TestClient, headers: dict[str, str], batch: dict[str, Any], target: str
) -> dict[str, Any]:
    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=headers).json()}
    matches = [
        {
            "kind": "product",
            "key": u["key"],
            "target_id": options[target if "Моцарелла" in u["name"] else "Сливки 33%"],
        }
        for u in batch["unmatched"]
    ]
    r = client.post(f"/api/imports/{batch['id']}/match", headers=headers, json={"matches": matches})
    body: dict[str, Any] = r.json()
    return body


def test_wrong_match_is_fixed_and_files_are_reprocessed(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    director, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    # A mistake: the 1С mozzarella matched to cream (both units would fail, so use the same unit family).
    text_1c = RECEIPTS_1C.replace(";кг;", ";л;")
    batch = upload(client, director, "receipts", text_1c, a1).json()
    publish(client, director, _match_all(client, director, batch, "Сливки 33%")["id"])

    rows = client.get("/api/aliases", headers=director).json()
    wrong = next(a for a in rows if a["source_text"].startswith("Моцарелла"))
    assert (wrong["target_name"], wrong["restaurant_id"], wrong["files"]) == ("Сливки 33%", str(a1), 1)

    # Fixing it lists the files built on it; re-processing makes the numbers follow the fix.
    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=director).json()}
    changed = client.put(
        f"/api/aliases/{wrong['id']}", headers=director, json={"target_id": options["Сыр Моцарелла"]}
    )
    assert [f["id"] for f in changed.json()["affected_files"]] == [batch["id"]]
    # Litres do not convert to the kilograms of mozzarella: the file must be corrected, not silently reloaded.
    assert client.post(f"/api/imports/{batch['id']}/reprocess", headers=director).status_code == 422


def test_reprocess_applies_the_fixed_match(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    director, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    only_mozz = "Дата;Номенклатура;Количество;Сумма\n01.10.2026;Моцарелла фиор ди латте 45%;5;3100\n"
    with owner_engine.begin() as c:  # a product with the same unit to be matched by mistake
        c.execute(
            text(
                "INSERT INTO products (tenant_id, code, name, base_unit) "
                "VALUES (:t, 'P9', 'Сыр Пармезан', 'kg')"
            ),
            {"t": network.a.id},
        )
    batch = upload(client, director, "receipts", only_mozz, a1).json()
    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=director).json()}
    key = batch["unmatched"][0]["key"]
    client.post(
        f"/api/imports/{batch['id']}/match",
        headers=director,
        json={"matches": [{"kind": "product", "key": key, "target_id": options["Сыр Пармезан"]}]},
    )
    publish(client, director, batch["id"])
    alias = client.get("/api/aliases", headers=director).json()[0]
    client.put(f"/api/aliases/{alias['id']}", headers=director, json={"target_id": options["Сыр Моцарелла"]})
    with owner_engine.begin() as c:  # a stale report: re-processing must bring it up to date
        c.execute(text("UPDATE import_batches SET rows_valid = 0, aliases_used = '[]'::jsonb"))
    again = client.post(f"/api/imports/{batch['id']}/reprocess", headers=director)
    assert again.status_code == 200 and again.json()["rows_valid"] == 1
    with owner_engine.connect() as c:
        used = c.execute(text("SELECT aliases_used FROM import_batches WHERE id = :b"), {"b": batch["id"]})
        assert used.scalar_one() == [f"product:{key}"]
        name = c.execute(
            text("SELECT p.name FROM receipts r JOIN products p ON p.id = r.product_id")
        ).scalar_one()
    assert name == "Сыр Моцарелла"


def test_alias_visibility_and_rights(client: TestClient, network: Network, catalog: None) -> None:
    hq, director1, director2 = (
        login(client, "admin@a.ru"),
        login(client, "director1@a.ru"),
        login(client, "director2@a.ru"),
    )
    hq_batch = upload(client, hq, "receipts", RECEIPTS_1C, network.a.restaurants["A3"]).json()
    _match_all(client, hq, hq_batch, "Сыр Моцарелла")  # network-wide
    own = upload(
        client,
        director1,
        "receipts",
        RECEIPTS_1C.replace("Сливки 33% (Молочный двор)", "Сливки жирн."),
        network.a.restaurants["A1"],
    ).json()
    _match_all(client, director1, own, "Сыр Моцарелла")  # A1 only: just the cream
    seen1 = {
        (a["source_text"], a["restaurant_id"] is None)
        for a in client.get("/api/aliases", headers=director1).json()
    }
    seen2 = {
        (a["source_text"], a["restaurant_id"] is None)
        for a in client.get("/api/aliases", headers=director2).json()
    }
    assert ("Сливки жирн.", False) in seen1 and ("Сливки жирн.", False) not in seen2
    assert ("Моцарелла фиор ди латте 45%", True) in seen1 and ("Моцарелла фиор ди латте 45%", True) in seen2
    network_alias = next(
        a for a in client.get("/api/aliases", headers=director1).json() if a["restaurant_id"] is None
    )
    assert client.delete(f"/api/aliases/{network_alias['id']}", headers=director1).status_code == 403
    a1_alias = next(a for a in client.get("/api/aliases", headers=director1).json() if a["restaurant_id"])
    assert client.delete(f"/api/aliases/{a1_alias['id']}", headers=director2).status_code == 404
    assert client.get("/api/aliases", headers=login(client, "admin@b.ru")).json() == []
    assert client.delete(f"/api/aliases/{network_alias['id']}", headers=hq).status_code == 200


def test_recipe_cycle_through_semi_finished_products_is_refused(client: TestClient, network: Network) -> None:
    hq = login(client, "admin@a.ru")
    products = "Код;Наименование;Базовая ед.;Тип\nS1;Соус;кг;п/ф\nS2;Основа;кг;п/ф\nT1;Томаты;кг;\n"
    publish(client, hq, upload(client, hq, "products", products).json()["id"])
    ok = "Код блюда;Код товара;Брутто;Действует с\nS1;T1;1,2;01.08.2026\nS1;S2;0,2;01.08.2026\n"
    publish(client, hq, upload(client, hq, "recipes", ok).json()["id"])
    looped = upload(
        client, hq, "recipes", "Код блюда;Код товара;Брутто;Действует с\nS2;S1;0,1;01.09.2026\n"
    ).json()
    assert looped["status"] == "failed"
    assert (
        "«Основа» → «Соус» → «Основа»" in looped["errors"][0]["message"]
        or "«Соус» → «Основа» → «Соус»" in looped["errors"][0]["message"]
    )


def test_transfers_are_stored_once_and_seen_by_both_restaurants(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    from app.core.db import RlsContext, apply_rls_context, get_sessionmaker

    a1, a2, a3 = (network.a.restaurants[c] for c in ("A1", "A2", "A3"))
    d1, d2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    sent = (
        "Дата;Откуда;Куда;Товар;Количество\n"
        "01.10.2026;A1;A2;Сыр Моцарелла;2\n"
        "02.10.2026;A2;A1;Сыр Моцарелла;1\n"
    )
    batch = upload(client, d1, "transfers", sent, a1).json()
    assert (batch["status"], batch["rows_valid"]) == ("validated", 1)
    publish(client, d1, batch["id"])
    # The receiver's export of the same transfers — byte for byte the same file: not a duplicate for
    # another restaurant; only incoming rows, so nothing is stored twice.
    other = upload(client, d2, "transfers", sent, a2).json()
    assert (other["status"], other["rows_valid"]) == ("validated", 1)  # A2's own outgoing row of 02.10
    publish(client, d2, other["id"])
    # Another tenant's restaurant cannot be named.
    foreign = upload(client, d1, "transfers", sent.replace(";A2;Сыр", ";B1;Сыр"), a1).json()
    assert foreign["status"] == "failed" and "неизвестный ресторан «B1»" in foreign["errors"][0]["message"]

    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM transfers")).scalar_one() == 2  # 01.10 A1→A2, 02.10 A2→A1

    def visible(director: str, restaurant: UUID) -> int:
        session = get_sessionmaker()()
        try:
            apply_rls_context(
                session, RlsContext(network.a.id, network.a.users[director], False, frozenset({restaurant}))
            )
            return int(session.execute(text("SELECT count(*) FROM transfers")).scalar_one())
        finally:
            session.rollback()
            session.close()

    assert visible("director1@a.ru", a1) == 2  # sent one, received one
    assert visible("director2@a.ru", a2) == 2
    assert visible("director3@a.ru", a3) == 0


def test_erp_iiko_sync_collapses_names_and_contract_prices_load(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq = login(client, "admin@a.ru")
    publish(
        client,
        hq,
        upload(client, hq, "suppliers", "Код;Название;ИНН\nS1;Сырный дом;7701234567\n").json()["id"],
    )
    # Two names of 1С:ERP — one per supplier — are one product of iiko.
    sync = (
        "Код ЕРП;Номенклатура ЕРП;Код iiko;Товар iiko\n"
        "1001;Моцарелла 1 (Сырный дом);P1;\n"
        "1002;Моцарелла 2 (Лактика);P1;\n"
    )
    batch = upload(client, hq, "name_sync", sync).json()
    assert batch["status"] == "validated", batch
    publish(client, hq, batch["id"])
    receipts = (
        "Дата;Поставщик;Товар;Количество;Ед. изм.;Сумма\n"
        "01.10.2026;Сырный дом;Моцарелла 1 (Сырный дом);1000;кг;620000\n"
        "02.10.2026;Сырный дом;Моцарелла 2 (Лактика);500;кг;315000\n"
    )
    r = upload(client, login(client, "director1@a.ru"), "receipts", receipts, network.a.restaurants["A1"])
    assert r.json()["status"] == "validated" and r.json()["unmatched"] == []
    # Contract price per gram is stored per base unit (kg).
    contract = "Поставщик;Код товара;Ед. изм.;Цена по договору;Действует с\nСырный дом;P1;г;0,6;01.09.2026\n"
    c = upload(client, hq, "contract_prices", contract).json()
    assert c["template"] == "contract_prices" and c["status"] == "validated", c
    publish(client, hq, c["id"])
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT price FROM contract_prices")).scalar_one() == Decimal("600.0000")
    assert (
        upload(client, login(client, "director1@a.ru"), "contract_prices", contract + " ").status_code == 403
    )

    # TC-REV-04: invoices at 620 and 630 ₽/kg against the contract's 600 — the check recomputes the overpay
    # from the stored invoices and contract prices, invoice by invoice.
    publish(client, login(client, "director1@a.ru"), r.json()["id"])
    assert client.post("/api/analytics/run", headers=hq).status_code == 202
    pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
    breach = next(f for f in pending if f["title"] == "Цена выше договорной: Сыр Моцарелла")
    v = client.get(f"/api/findings/{breach['id']}/verification", headers=hq).json()
    assert v["supported"] and all(c["ok"] for c in v["checks"]) and all(r["passed"] for r in v["rules"])
    assert [(row["price"], row["contract"], row["overpay"]) for row in v["steps"][0]["rows"]] == [
        ("620.00", "600.00", "20000.00"),
        ("630.00", "600.00", "15000.00"),
    ]


def test_another_restaurant_or_network_cannot_match_reprocess_or_roll_back_a_file(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    """TC-ISO-10 (CLAUDE.md, principle 2): actions on someone else's file look like a missing file — 404 —
    and change nothing; the same for someone else's name match."""
    director, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    waiting = upload(client, director, "receipts", RECEIPTS_1C, a1).json()  # needs matching
    published = upload(client, director, "sales", SALES, a1).json()
    publish(client, director, published["id"])
    options = {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=director).json()}
    body = {
        "matches": [
            {"kind": "product", "key": u["key"], "target_id": options["Сыр Моцарелла"]}
            for u in waiting["unmatched"]
        ]
    }
    for stranger in (
        login(client, "director2@a.ru"),
        login(client, "admin@b.ru"),
        login(client, "director1@b.ru"),
    ):
        assert client.get(f"/api/imports/{waiting['id']}", headers=stranger).status_code == 404
        assert (
            client.post(f"/api/imports/{waiting['id']}/match", headers=stranger, json=body).status_code == 404
        )
        assert client.post(f"/api/imports/{waiting['id']}/publish", headers=stranger).status_code == 404
        for action in ("reprocess", "rollback"):
            answer = client.post(f"/api/imports/{published['id']}/{action}", headers=stranger)
            assert answer.status_code == 404, (action, answer.text)
    # Nothing moved: the file still waits for its names, the sales are still there, no match was remembered.
    assert client.get(f"/api/imports/{waiting['id']}", headers=director).json()["status"] == "needs_matching"
    assert client.get(f"/api/imports/{published['id']}", headers=director).json()["status"] == "published"
    assert _sales_count(owner_engine) == 2
    assert client.get("/api/aliases", headers=director).json() == []

    # A name match of network A: tenant B can neither change nor delete it.
    _match_all(client, director, waiting, "Сыр Моцарелла")
    alias = client.get("/api/aliases", headers=director).json()[0]
    foreign = login(client, "admin@b.ru")
    assert (
        client.put(
            f"/api/aliases/{alias['id']}", headers=foreign, json={"target_id": options["Сливки 33%"]}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/aliases/{alias['id']}", headers=foreign).status_code == 404
    assert client.get("/api/aliases", headers=director).json()[0]["target_name"] == alias["target_name"]
