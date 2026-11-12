"""Units of the exports per product (Q35): the HQ sets «1 упак = 2,5 кг» once, imports convert by it; a unit
without a factor is an error the report can fix on the spot; a changed factor names the files built on it."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.period import get_today
from app.imports import validate
from app.main import app
from tests.conftest import Network, login
from tests.test_imports_api import PRODUCTS, publish, upload

TODAY = date(2026, 10, 25)
RECEIPTS = (
    "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n"
    "01.10.2026;Сыр Моцарелла;4;Упак.;3100\n"
    "02.10.2026;Сыр Моцарелла;2;упак;1550\n"
    "02.10.2026;Сливки 33%;6;бут 0,5;720\n"
)


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


@pytest.fixture
def products(client: TestClient, network: Network) -> dict[str, str]:
    hq = login(client, "admin@a.ru")
    publish(client, hq, upload(client, hq, "products", PRODUCTS).json()["id"])
    return {o["name"]: o["id"] for o in client.get("/api/catalog/product", headers=hq).json()}


def _save(client: TestClient, headers: dict[str, str], product_id: str, unit: str, factor: str) -> Any:
    return client.put(
        "/api/settings/units",
        headers=headers,
        json={"product_id": product_id, "unit_text": unit, "factor": factor},
    )


def _qty(owner_engine: Engine) -> list[tuple[str, Decimal]]:
    with owner_engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT p.name, r.qty FROM receipts r JOIN products p ON p.id = r.product_id "
                "ORDER BY r.day, p.name"
            )
        ).all()
    return [(n, q) for n, q in rows]


def test_a_unit_without_a_factor_is_an_error_the_report_can_fix(
    client: TestClient, network: Network, products: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-39: «упак» and «бут 0,5» are not guessed; the report names each product and unit once, the HQ
    sets the factors, «Проверить заново» passes the same file, quantities are in base units."""
    director, hq, a1 = (
        login(client, "director1@a.ru"),
        login(client, "admin@a.ru"),
        network.a.restaurants["A1"],
    )
    batch = upload(client, director, "receipts", RECEIPTS, a1).json()
    assert batch["status"] == "failed" and len(batch["errors"]) == 3
    assert "задайте, сколько кг в 1 «Упак.»" in batch["errors"][0]["message"]
    fixes = {(f["product_name"], f["unit"]): f for f in batch["unit_fixes"]}
    assert set(fixes) == {("Сыр Моцарелла", "упак"), ("Сливки 33%", "бут 0 5")}
    assert (
        fixes[("Сыр Моцарелла", "упак")]["rows"] == 2 and fixes[("Сливки 33%", "бут 0 5")]["base_unit"] == "l"
    )

    # A director cannot set the network's factors; an analyst cannot either.
    mozz, cream = products["Сыр Моцарелла"], products["Сливки 33%"]
    assert _save(client, director, mozz, "упак", "2,5").status_code == 403
    assert _save(client, login(client, "analyst@a.ru"), mozz, "упак", "2,5").status_code == 403
    assert _save(client, hq, mozz, "Упак", "2,5").status_code == 200
    # Half the factors: the file still fails, now on the cream only.
    half = client.post(f"/api/imports/{batch['id']}/recheck", headers=director).json()
    assert half["status"] == "failed" and [f["product_name"] for f in half["unit_fixes"]] == ["Сливки 33%"]
    assert _save(client, hq, cream, "бут 0,5", "0.5").status_code == 200
    again = client.post(f"/api/imports/{batch['id']}/recheck", headers=director).json()
    assert again["status"] == "validated" and again["errors"] == [] and again["unit_fixes"] == []
    publish(client, director, batch["id"])
    assert _qty(owner_engine) == [
        ("Сыр Моцарелла", Decimal("10.0000")),
        ("Сливки 33%", Decimal("3.0000")),
        ("Сыр Моцарелла", Decimal("5.0000")),
    ]
    # Only a failed file is checked again.
    assert client.post(f"/api/imports/{batch['id']}/recheck", headers=director).status_code == 422


def test_a_changed_factor_names_the_files_to_reprocess(
    client: TestClient, network: Network, products: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-40: the list shows each factor with the files converted by it; changing or deleting it returns
    those files, «Пересчитать» follows the new value; one factor per product and unit."""
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    mozz = products["Сыр Моцарелла"]
    _save(client, hq, mozz, "упак", "2.5")
    _save(client, hq, products["Сливки 33%"], "бут 0,5", "0.5")
    batch = upload(client, hq, "receipts", RECEIPTS, a1).json()
    publish(client, hq, batch["id"])

    listed = {f["unit"]: f for f in client.get("/api/settings/units", headers=hq).json()}
    assert listed["упак"]["files"] == 1 and listed["упак"]["factor"] == "2.5"
    assert listed["упак"]["product_name"] == "Сыр Моцарелла" and listed["упак"]["base_unit"] == "kg"
    changed = _save(client, hq, mozz, "УПАК.", "3").json()
    assert changed["factor"]["id"] == listed["упак"]["id"] and changed["factor"]["unit_text"] == "УПАК."
    assert [f["id"] for f in changed["affected_files"]] == [batch["id"]]
    assert len(client.get("/api/settings/units", headers=hq).json()) == 2
    assert client.post(f"/api/imports/{batch['id']}/reprocess", headers=hq).status_code == 200
    assert [q for n, q in _qty(owner_engine) if n == "Сыр Моцарелла"] == [
        Decimal("12.0000"),
        Decimal("6.0000"),
    ]

    # A factor files were loaded with is not deleted: they would no longer pass (backend review, p. 4).
    in_use = client.delete(f"/api/settings/units/{listed['бут 0 5']['id']}", headers=hq)
    assert in_use.status_code == 409 and "загружено файлов: 1" in in_use.text
    spare = _save(client, hq, products["Сливки 33%"], "кор", "10").json()["factor"]
    assert spare["factor"] == "10"  # never «1E+1» (p. 6)
    gone = client.delete(f"/api/settings/units/{spare['id']}", headers=hq)
    assert gone.status_code == 200 and gone.json()["affected_files"] == []
    assert client.delete(f"/api/settings/units/{spare['id']}", headers=hq).status_code == 404


@pytest.mark.parametrize(
    ("unit", "factor", "message"),
    [
        ("упак", "0", "больше нуля"),
        ("упак", "-1", "больше нуля"),
        ("упак", "много", "число"),
        ("упак", "20000", "больше 10 000"),
        ("упак", "0.0000001", "шести знаков"),
        ("кг", "1", "и так переводится в кг"),
        ("г", "0.001", "и так переводится в кг"),
        ("   ", "1", "Укажите единицу"),
    ],
)
def test_a_factor_is_a_sane_positive_number(
    client: TestClient, network: Network, products: dict[str, str], unit: str, factor: str, message: str
) -> None:
    """TC-IMP-41: zero, negative, text, huge factors and standard units of the same kind are refused."""
    r = _save(client, login(client, "admin@a.ru"), products["Сыр Моцарелла"], unit, factor)
    assert r.status_code == 422 and message in r.text


def test_a_standard_unit_of_another_kind_takes_the_products_factor(
    client: TestClient, network: Network, products: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-42: «шт» of a product kept in kg converts by the factor too; the factors are the network's own —
    another network neither sees them nor converts by them; an unknown product is 404."""
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    assert _save(client, hq, products["Сыр Моцарелла"], "шт", "0.125").status_code == 200
    content = "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n01.10.2026;Сыр Моцарелла;8;шт;620\n"
    batch = upload(client, hq, "receipts", content, a1).json()
    assert batch["status"] == "validated"
    publish(client, hq, batch["id"])
    assert _qty(owner_engine) == [("Сыр Моцарелла", Decimal("1.0000"))]

    other = login(client, "admin@b.ru")
    assert client.get("/api/settings/units", headers=other).json() == []
    assert _save(client, other, products["Сыр Моцарелла"], "шт", "1").status_code == 404
    hq_b = upload(client, other, "products", PRODUCTS).json()
    publish(client, other, hq_b["id"])
    b_batch = upload(client, other, "receipts", content, network.b.restaurants["B1"]).json()
    assert b_batch["status"] == "failed" and b_batch["unit_fixes"][0]["unit"] == "шт"


def test_every_unit_without_a_factor_is_asked_for_past_the_shown_errors(
    client: TestClient, network: Network, products: dict[str, str]
) -> None:
    """TC-IMP-39 (backend review of stage 10, p. 7): 250 rows of «упак» and then one of «бут» — the report
    shows 200 errors, yet asks for both factors with the count of all their rows."""
    rows = ["01.10.2026;Сыр Моцарелла;1;упак;100"] * 250 + ["02.10.2026;Сливки 33%;1;бут;100"]
    content = "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n" + "\n".join(rows) + "\n"
    batch = upload(
        client, login(client, "admin@a.ru"), "receipts", content, network.a.restaurants["A1"]
    ).json()
    assert {(f["unit"], f["rows"]) for f in batch["unit_fixes"]} == {("упак", 250), ("бут", 1)}


# ------------------------------------------------------------------ test engineer after the stage 10 review


def test_recheck_of_a_file_whose_source_was_purged_says_so(
    client: TestClient, network: Network, products: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-43: a failed file is kept 7 days (Q37); past that its bytes are gone, and «Проверить заново»
    says to upload it again instead of checking an empty file — the report stays as it was."""
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    batch = upload(client, hq, "receipts", RECEIPTS, a1).json()
    with owner_engine.begin() as c:
        c.execute(
            text("UPDATE import_batches SET raw = '', raw_deleted_at = now() WHERE id = :id"),
            {"id": batch["id"]},
        )
    _save(client, hq, products["Сыр Моцарелла"], "упак", "2.5")
    _save(client, hq, products["Сливки 33%"], "бут 0,5", "0.5")
    r = client.post(f"/api/imports/{batch['id']}/recheck", headers=hq)
    assert r.status_code == 422 and "удален по сроку хранения" in r.text and "загрузите его заново" in r.text
    again = client.get(f"/api/imports/{batch['id']}", headers=hq).json()
    assert again["status"] == "failed" and len(again["unit_fixes"]) == 2


def test_a_recheck_that_would_load_the_same_file_twice_is_a_duplicate(
    client: TestClient, network: Network, products: dict[str, str]
) -> None:
    """TC-IMP-43: the same failed file uploaded twice for A1 (a failed file is no duplicate); once the first
    passes the check, the second is the same file — 409 «уже загружен», and it stays failed. For A2 the same
    file is not a duplicate (Q35 changes nothing in that rule)."""
    hq, a1, a2 = login(client, "admin@a.ru"), network.a.restaurants["A1"], network.a.restaurants["A2"]
    first, second = (upload(client, hq, "receipts", RECEIPTS, a1).json() for _ in range(2))
    other = upload(client, hq, "receipts", RECEIPTS, a2).json()
    assert first["id"] != second["id"] and {first["status"], second["status"]} == {"failed"}
    _save(client, hq, products["Сыр Моцарелла"], "упак", "2.5")
    _save(client, hq, products["Сливки 33%"], "бут 0,5", "0.5")
    assert client.post(f"/api/imports/{first['id']}/recheck", headers=hq).json()["status"] == "validated"
    dup = client.post(f"/api/imports/{second['id']}/recheck", headers=hq)
    assert dup.status_code == 409 and "уже загружен для этого ресторана" in dup.text
    assert client.get(f"/api/imports/{second['id']}", headers=hq).json()["status"] == "failed"
    assert client.post(f"/api/imports/{other['id']}/recheck", headers=hq).json()["status"] == "validated"


def test_a_recheck_and_the_factors_stay_within_the_restaurant_and_the_network(
    client: TestClient, network: Network, products: dict[str, str]
) -> None:
    """TC-IMP-42: a director checks again only a file of their own restaurant; another network neither
    deletes nor changes the network's factor (404), nor checks its file again, and the factor stays."""
    hq, a1, a2 = login(client, "admin@a.ru"), network.a.restaurants["A1"], network.a.restaurants["A2"]
    batch = upload(client, hq, "receipts", RECEIPTS, a2).json()
    factor = _save(client, hq, products["Сыр Моцарелла"], "упак", "2.5").json()["factor"]
    director1 = login(client, "director1@a.ru")
    assert client.post(f"/api/imports/{batch['id']}/recheck", headers=director1).status_code in (403, 404)
    assert upload(client, director1, "receipts", RECEIPTS, a1).status_code == 201  # their own: allowed

    b = login(client, "admin@b.ru")
    assert client.delete(f"/api/settings/units/{factor['id']}", headers=b).status_code == 404
    assert _save(client, b, products["Сыр Моцарелла"], "упак", "9").status_code == 404
    assert client.post(f"/api/imports/{batch['id']}/recheck", headers=b).status_code == 404
    (kept,) = client.get("/api/settings/units", headers=hq).json()
    assert (kept["id"], kept["factor"]) == (factor["id"], "2.5")
    # A director and an analyst of A read the list (docs/04: «видят список, но не меняют его»).
    for who in ("director1@a.ru", "analyst@a.ru"):
        assert [f["id"] for f in client.get("/api/settings/units", headers=login(client, who)).json()] == [
            factor["id"]
        ]


def test_a_unit_is_compared_without_case_and_dots_but_with_its_volume(
    client: TestClient, network: Network, products: dict[str, str]
) -> None:
    """TC-IMP-39 (docs/04): «Бут.» and «бут» are one unit, «бут 0,5» another — a factor for «бут» does not
    convert «бут 0,5»; a unit longer than 40 characters is refused."""
    hq, a1, cream = login(client, "admin@a.ru"), network.a.restaurants["A1"], products["Сливки 33%"]
    assert _save(client, hq, cream, "бут", "1").status_code == 200
    content = "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n02.10.2026;Сливки 33%;6;Бут.;720\n"
    assert upload(client, hq, "receipts", content, a1).json()["status"] == "validated"
    half = content.replace("Бут.", "бут 0,5")
    failed = upload(client, hq, "receipts", half, a1).json()
    assert failed["status"] == "failed" and [f["unit"] for f in failed["unit_fixes"]] == ["бут 0 5"]
    long = _save(client, hq, cream, "у" * 41, "1")
    assert long.status_code == 422


def test_unit_fixes_count_rows_once_per_product_and_unit() -> None:
    """TC-IMP-39: the report's list of units — the check's count of all rows of a pair is taken as it is
    (repeats with 0 add nothing); a report saved before the counts counts the rows shown; other errors are
    not in it."""
    from app.imports.api import unit_fixes

    fix = {"kind": "unit_factor", "product_id": str(uuid4()), "unit": "упак", "unit_text": "упак"}
    fix |= {"product_name": "Сыр", "base_unit": "kg"}
    other = {**fix, "product_id": str(uuid4()), "product_name": "Сливки"}
    errors = [
        {"row": 2, "message": "…", "fix": {**fix, "rows": 250}},
        {"row": 3, "message": "…", "fix": {**fix, "rows": 0}},
        {"row": 4, "message": "дата в будущем"},
        {"row": 5, "message": "…", "fix": {"kind": "other"}},
    ]
    assert [(f.product_name, f.rows) for f in unit_fixes(errors)] == [("Сыр", 250)]
    old = [{"row": i, "message": "…", "fix": other} for i in range(3)]
    assert [(f.product_name, f.rows) for f in unit_fixes(old)] == [("Сливки", 3)]


def test_past_the_error_cap_the_count_of_the_rest_is_right(
    client: TestClient, network: Network, products: dict[str, str]
) -> None:
    """TC-IMP-39 (backend review of stage 10, p. 7): 250 rows of «упак» and one of «бут» are 251 errors: 200
    are shown, the first «бут» row is added for its factor — so «и еще 50», not 51."""
    rows = ["01.10.2026;Сыр Моцарелла;1;упак;100"] * 250 + ["02.10.2026;Сливки 33%;1;бут;100"]
    content = "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n" + "\n".join(rows) + "\n"
    batch = upload(
        client, login(client, "admin@a.ru"), "receipts", content, network.a.restaurants["A1"]
    ).json()
    *listed, tail = batch["errors"]
    assert len(listed) == 201 and listed[-1]["row"] == 252  # the header is row 1
    hidden = 251 - len(listed)
    assert tail["message"] == f"и еще {validate._errors(hidden)} того же рода"
    assert [validate._errors(n) for n in (1, 3, 11, 21, 50)] == [
        "1 ошибка",
        "3 ошибки",
        "11 ошибок",
        "21 ошибка",
        "50 ошибок",
    ]
    # 200 rows of «упак» and one of «бут»: every error is listed, there is no «и еще 0».
    rows = ["01.10.2026;Сыр Моцарелла;1;упак;100"] * 200 + ["02.10.2026;Сливки 33%;1;бут;100"]
    content = "Дата;Номенклатура;Количество;Ед. изм.;Сумма\n" + "\n".join(rows) + "\n"
    batch = upload(
        client, login(client, "admin@a.ru"), "receipts", content, network.a.restaurants["A1"], "g.csv"
    ).json()
    assert len(batch["errors"]) == 201 and not batch["errors"][-1]["message"].startswith("и еще")
