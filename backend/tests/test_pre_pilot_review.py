"""Code review before the pilot (docs/reviews/2026-11-10-pre-pilot-review.md): each fix with its test.

TC-IMP-26…35, TC-AUTH-11…13, TC-AI-39.
"""

import io
from collections.abc import Iterator
from datetime import date

import pytest
import xlsxwriter
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.ai.mapping import MASK, masked_samples
from app.catalog.models import MenuItem, Product, RecipeLine
from app.core import limits
from app.core.errors import InvalidError
from app.core.period import get_today
from app.imports import service
from app.imports.reader import MAX_ROWS, read_rows
from app.main import app
from tests.conftest import PASSWORD, Network, login
from tests.test_imports_api import publish, upload

TODAY = date(2026, 10, 25)
PRODUCTS = "Код;Наименование;Категория;Базовая ед.\nP1;Сыр Моцарелла;Сыры;кг\nP2;Сливки 33%;Молочные;л\n"
MENU = "Код;Блюдо;Категория;Цена\nM1;Маргарита;Пицца;580\n"


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


@pytest.fixture
def hq(client: TestClient, network: Network) -> dict[str, str]:
    auth = login(client, "admin@a.ru")
    for template, content in (("products", PRODUCTS), ("menu_items", MENU)):
        publish(client, auth, upload(client, auth, template, content).json()["id"])
    return auth


def _xlsx(cells: dict[tuple[int, int], str]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet()
    for (r, c), v in cells.items():
        ws.write(r, c, v)
    wb.close()
    return buf.getvalue()


# ------------------------------------------------------------------ reading files


def test_a_tiny_workbook_with_a_far_cell_is_refused_before_it_fills_the_memory() -> None:
    """TC-IMP-26 (p. 2): 5 KB with a cell at ALL10000 would be 10 million cells in memory."""
    with pytest.raises(InvalidError, match="слишком большая"):
        read_rows(_xlsx({(0, 0): "Дата", (9_999, 999): "x"}), "bomb.xlsx")
    with pytest.raises(InvalidError, match="слишком большая"):
        read_rows(_xlsx({(0, 0): "Дата", (MAX_ROWS + 5, 1): "x"}), "long.xlsx")
    assert read_rows(_xlsx({(0, 0): "Дата", (2, 3): "x"}), "ok.xlsx")[2][3] == "x"


def test_the_csv_separator_is_the_one_that_cuts_rows_evenly() -> None:
    """TC-IMP-27 (p. 13): commas in a dish name and decimal commas do not win over «;»."""
    raw = "Дата;Блюдо;Кол-во;Сумма\n01.10.2026;Пицца Маргарита, 30 см, тонкое тесто;1,5;100,50\n".encode()
    assert read_rows(raw, "s.csv")[1] == [
        "01.10.2026",
        "Пицца Маргарита, 30 см, тонкое тесто",
        "1,5",
        "100,50",
    ]
    assert read_rows(b"a,b,c\n1,2,3\n", "s.csv")[1] == ["1", "2", "3"]
    assert read_rows("Дата\tБлюдо\n1\t2\n".encode("utf-16"), "u.csv") == [["Дата", "Блюдо"], ["1", "2"]]


def test_unreadable_files_are_said_in_russian_never_a_500() -> None:
    """TC-IMP-28 (p. 14): a field over csv's limit, a broken workbook — no English of the library."""
    with pytest.raises(InvalidError, match="CSV"):
        read_rows(b'a;b\n"' + b"x" * 200_000 + b'"\n', "big.csv")
    with pytest.raises(InvalidError) as e:
        read_rows(b"PK\x03\x04 not really a zip", "broken.xlsx")
    assert "xlsx" in str(e.value) and "Error" not in str(e.value)


# ------------------------------------------------------------------ rows and periods


def test_one_typo_in_a_year_cannot_replace_ten_years_of_data(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-29 (p. 6): a day far from all the others is an error of its row, not the file's period."""
    rows = "\n".join(f"{d:02d}.10.2026;Маргарита;3;1740" for d in range(1, 20))
    r = upload(
        client,
        hq,
        "sales",
        f"Дата;Блюдо;Кол-во;Сумма\n{rows}\n01.10.2016;Маргарита;1;580\n",
        network.a.restaurants["A1"],
    )
    body = r.json()
    assert body["status"] == "failed"
    assert [e["row"] for e in body["errors"]] == [21] and "проверьте год" in body["errors"][0]["message"]
    assert "01.10.2026–19.10.2026" in body["errors"][0]["message"]


def test_stock_counts_one_to_three_months_apart_are_one_period(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-29: counts on 01.06 and 03.08 (63 days) are a normal file, not a typo."""
    content = "Дата;Код товара;Фактический остаток\n01.06.2026;P1;10\n03.08.2026;P1;12\n"
    r = upload(client, hq, "inventory_counts", content, network.a.restaurants["A1"])
    assert r.json()["status"] == "validated", r.json()["errors"]


def test_values_the_database_cannot_hold_are_errors_of_their_rows(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-30 (p. 11): a barcode in «Количество», 0,00001 кг, «1E+1000000», a reason of 500 letters."""
    content = (
        "Дата;Код товара;Количество;Ед. изм.;Причина\n"
        "01.10.2026;P1;46070000123456;кг;Порча\n"
        "02.10.2026;P1;0,00001;кг;Порча\n"
        "03.10.2026;P1;1E+1000000;кг;Порча\n"
        f"04.10.2026;P1;1;кг;{'о' * 500}\n"
        "05.10.2026;P1;1;кг;Порча\n"
    )
    body = upload(client, hq, "write_offs", content, network.a.restaurants["A1"]).json()
    assert body["status"] == "failed"
    assert sorted(e["row"] for e in body["errors"]) == [2, 3, 4, 5]
    messages = " ".join(e["message"] for e in body["errors"])
    assert "слишком большое число" in messages and "0,0001" in messages and "до 200" in messages


def test_an_ingredient_twice_in_a_recipe_is_summed_not_a_failed_publish(
    client: TestClient, hq: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-31 (p. 10): cheese inside and on top — one line with the sum and a warning."""
    content = (
        "Код блюда;Код товара;Брутто;Ед. изм.;Действует с\nM1;P1;0,10;кг;01.01.2026\nM1;P1;40;г;01.01.2026\n"
    )
    body = upload(client, hq, "recipes", content).json()
    assert body["status"] == "validated"
    assert any("повторяется" in w["message"] for w in body["warnings"])
    publish(client, hq, body["id"])
    with Session(owner_engine) as s:
        assert [str(q) for q in s.execute(select(RecipeLine.gross_qty)).scalars()] == ["0.1400"]


# ------------------------------------------------------------------ reference data


def test_a_name_two_items_share_is_matched_by_a_person_never_at_random(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-32 (p. 7): «Капучино» in two groups; a sale by name only asks which one."""
    menu = "Код;Блюдо;Категория\nM2;Капучино;Кофе\nM3;Капучино;Завтраки\n"
    publish(client, hq, upload(client, hq, "menu_items", menu).json()["id"])
    sales = "Дата;Блюдо;Кол-во;Сумма\n01.10.2026;Капучино;2;400\n02.10.2026;Маргарита;1;580\n"
    body = upload(client, hq, "sales", sales, network.a.restaurants["A1"]).json()
    assert body["status"] == "needs_matching"
    assert [u["name"] for u in body["unmatched"]] == ["Капучино"]


def test_a_reference_file_without_a_column_keeps_what_it_does_not_say(
    client: TestClient, hq: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-33 (p. 8): products without «Категория», a menu without «Цена» — categories and prices stay."""
    publish(
        client,
        hq,
        upload(client, hq, "products", "Код;Наименование;Базовая ед.\nP1;Моцарелла;кг\n").json()["id"],
    )
    publish(client, hq, upload(client, hq, "menu_items", "Код;Блюдо\nM1;Пицца Маргарита\n").json()["id"])
    with Session(owner_engine) as s:
        p = s.execute(select(Product).where(Product.code == "P1")).scalar_one()
        m = s.execute(select(MenuItem).where(MenuItem.code == "M1")).scalar_one()
        assert (p.name, p.category) == ("Моцарелла", "Сыры")
        assert (m.name, m.category, str(m.price)) == ("Пицца Маргарита", "Пицца", "580.00")


def test_a_reference_file_over_the_parameters_of_one_statement_is_published(
    client: TestClient, hq: dict[str, str], owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-IMP-34 (p. 9): 10 000 × 7 parameters is over psycopg's 65 535 in one INSERT: written in parts."""
    lines = "\n".join(f"X{i:05d};Товар {i};Бакалея;кг;30;товар" for i in range(10_000))
    content = f"Код;Наименование;Категория;Базовая ед.;Срок годности, дней;Тип\n{lines}\n"
    body = upload(client, hq, "products", content).json()
    assert body["status"] == "validated"
    publish(client, hq, body["id"])
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM products WHERE code LIKE 'X%'")).scalar_one() == 10_000
    assert service.CHUNK * 7 < 65_535


def test_a_second_upload_of_reference_data_says_the_network(client: TestClient, hq: dict[str, str]) -> None:
    """TC-IMP-35 (frontend p. 14): «уже загружен для сети», not «для этого ресторана»."""
    r = upload(client, hq, "products", PRODUCTS)
    assert r.status_code == 409 and "для сети" in r.json()["detail"]


# ------------------------------------------------------------------ the server's limits


def test_a_body_over_the_limit_is_refused_before_it_is_read(client: TestClient) -> None:
    """TC-AUTH-11 (p. 1): no token, a «file» of 22 MB — 413 at once, nothing spooled to disk."""
    r = client.post(
        "/api/imports",
        content=b"x" * (limits.UPLOAD_LIMIT + 1),
        headers={"Content-Type": "multipart/form-data"},
    )
    assert r.status_code == 413 and "20 МБ" in r.json()["detail"]
    r = client.post("/api/auth/login", content=b"{" + b" " * (limits.BODY_LIMIT + 1) + b"}")
    assert r.status_code == 413

    def chunks() -> Iterator[bytes]:  # no Content-Length: counted while it is read
        for _ in range(limits.BODY_LIMIT // 65_536 + 2):
            yield b" " * 65_536

    r = client.post("/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_the_eleventh_failed_sign_in_waits(client: TestClient, network: Network) -> None:
    """TC-AUTH-12 (p. 3): ten wrong passwords for an email, then 429 even with the right one."""
    for _ in range(limits.MAX_FAILURES):
        r = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": "wrong-pass"})
        assert r.status_code == 401 and r.json()["detail"] == "Неверный email или пароль"
    r = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": PASSWORD})
    assert r.status_code == 429 and "подождите" in r.json()["detail"]
    limits.login_guard._failures.clear()
    assert (
        client.post("/api/auth/login", json={"email": "admin@a.ru", "password": PASSWORD}).status_code == 200
    )


def test_the_api_speaks_russian_when_it_refuses(client: TestClient, network: Network) -> None:
    """TC-AUTH-13 (frontend p. 1): no token, a bad token, a form it cannot read."""
    assert client.get("/api/auth/me").json()["detail"] == "Войдите в систему"
    r = client.post("/api/auth/refresh", json={"refresh_token": "nonsense"})
    assert r.json()["detail"] == "Сессия закончилась — войдите снова"
    r = client.post("/api/auth/login", json={"email": "admin@a.ru"})
    assert r.status_code == 422 and r.json()["detail"].startswith("Сервер не принял данные")


def test_login_guard_bounds_hashes_at_once() -> None:
    guard = limits.LoginGuard()
    held = [guard._hashing.acquire(timeout=0) for _ in range(limits.HASHES_AT_ONCE)]
    assert all(held)
    original = limits.WAIT_FOR_HASH
    limits.WAIT_FOR_HASH = 0.01
    try:
        with pytest.raises(limits.TooManyError), guard.hashing():
            pass
    finally:
        limits.WAIT_FOR_HASH = original
    assert limits.client_address({"x-forwarded-for": "10.0.0.7, 172.18.0.2"}, "172.18.0.2") == "10.0.0.7"
    assert limits.client_address({}, None) == "?"


# ------------------------------------------------------------------ personal data


def test_the_model_never_sees_the_names_of_cashiers() -> None:
    """TC-AI-39 (p. 12): the samples of a file to mark — cashiers' columns and full names are masked."""
    header = ["Дата", "Блюдо", "Официант", "Комментарий", "Сумма"]
    rows = [["01.10.2026", "Пицца Маргарита", "таб. 101", "Иванов И.И.", "580"]]
    assert masked_samples(header, rows) == [["01.10.2026", "Пицца Маргарита", MASK, MASK, "580"]]
