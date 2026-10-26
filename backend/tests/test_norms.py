"""Norms of the network: defaults, admin-only changes, tenant isolation, write-off reasons in import."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.norms.service import Norms
from tests.conftest import Network, login
from tests.test_imports_api import PRODUCTS, publish, upload


def test_defaults_are_the_agreed_values() -> None:
    norms = Norms()
    assert norms.food_cost_target("Пицца") == Decimal(30)
    assert norms.loss_allowance("Овощи") == Decimal(3)
    assert norms.loss_allowance("Мясо и птица") == Decimal(2)
    assert norms.loss_allowance("Напитки") == Decimal(1)
    assert norms.loss_allowance(None) == norms.loss_default_pct


def test_reasons_of_an_export_map_to_standard_ones() -> None:
    norms = Norms()
    assert norms.classify("Порча") == "spoilage"
    assert norms.classify("Истек срок годности") == "spoilage"
    assert norms.classify("ПИТАНИЕ ПЕРСОНАЛА") == "staff_meal"
    assert norms.classify("Бой посуды с продуктом") == "breakage"
    assert norms.classify("Недостача по инвентаризации") == "shortage"
    assert norms.classify("Что-то свое") == "other"
    assert norms.classify(None) == "other"


def _body(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    r = client.get("/api/settings/norms", headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def test_admin_changes_norms_others_only_read(client: TestClient, network: Network) -> None:
    hq = login(client, "admin@a.ru")
    body = _body(client, hq)
    assert Decimal(str(body["food_cost_target_pct"])) == 30
    body["food_cost_by_category"] = {"Пицца": "28"}
    body["loss_by_category"] = {"Овощи": "4"}
    body["write_off_reasons"] = [
        {"code": "spoilage", "title": "Порча", "kind": "loss", "synonyms": ["испорчено"]},
        {"code": "promo", "title": "Промо", "kind": "planned", "synonyms": ["акция"]},
    ]
    saved = client.put("/api/settings/norms", headers=hq, json=body)
    assert saved.status_code == 200, saved.text
    assert Decimal(saved.json()["food_cost_by_category"]["Пицца"]) == 28
    # «Прочее» is always there: unknown reasons need a place to go.
    assert [r["code"] for r in saved.json()["write_off_reasons"]] == ["spoilage", "promo", "other"]

    director = login(client, "director1@a.ru")
    assert Decimal(str(_body(client, director)["loss_by_category"]["Овощи"])) == 4  # type: ignore[index]
    assert client.put("/api/settings/norms", headers=director, json=body).status_code == 403
    assert (
        client.put("/api/settings/norms", headers=login(client, "analyst@a.ru"), json=body).status_code == 403
    )
    # Another network keeps its own (default) norms.
    other = _body(client, login(client, "admin@b.ru"))
    assert other["food_cost_by_category"] == {} and Decimal(str(other["loss_by_category"]["Овощи"])) == 3  # type: ignore[index]


def test_invalid_norms_are_refused(client: TestClient, network: Network) -> None:
    hq = login(client, "admin@a.ru")
    body = _body(client, hq)
    assert (
        client.put("/api/settings/norms", headers=hq, json={**body, "food_cost_target_pct": 120}).status_code
        == 422
    )
    twice = [{"code": "x", "title": "А", "kind": "loss"}, {"code": "x", "title": "Б", "kind": "loss"}]
    assert (
        client.put("/api/settings/norms", headers=hq, json={**body, "write_off_reasons": twice}).status_code
        == 422
    )


def test_import_classifies_write_off_reasons_and_warns_about_unknown(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    hq = login(client, "admin@a.ru")
    publish(client, hq, upload(client, hq, "products", PRODUCTS).json()["id"])
    director = login(client, "director1@a.ru")
    content = (
        "Дата;Код товара;Товар;Количество;Ед. изм.;Причина\n"
        "01.10.2026;P1;Сыр Моцарелла;0,5;кг;Порча\n"
        "02.10.2026;P1;Сыр Моцарелла;0,2;кг;Питание персонала\n"
        "03.10.2026;P2;Сливки 33%;0,3;л;Списание по акту 5\n"
    )
    r = upload(client, director, "write_offs", content, network.a.restaurants["A1"])
    assert r.status_code == 201, r.text
    assert any("«Списание по акту 5»" in w["message"] for w in r.json()["warnings"])
    publish(client, director, r.json()["id"])
    with owner_engine.connect() as c:
        codes = c.execute(text("SELECT reason_code FROM write_offs ORDER BY day")).scalars().all()
    assert codes == ["spoilage", "staff_meal", "other"]
