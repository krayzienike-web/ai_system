"""Stage 6.5 exports (docs/09): «Остатки на дату» (iiko), «Удаления и отмены» (r_keeper), the cashier of a
sale — loaded like the other facts of a restaurant: checked row by row, idempotent, under the restaurant's
row-level security (TC-IMP-20…)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.imports.validate import after_print
from tests.conftest import Network, login
from tests.test_imports_api import _pin_today, publish, upload  # noqa: F401  (a fixture)
from tests.test_imports_api import catalog as catalog

STOCK = "На дату;Товар;Остаток;Ед. изм.\n05.10.2026;Сыр Моцарелла;12,5;кг\n06.10.2026;Сыр Моцарелла;9;кг\n"
VOIDS = (
    "Дата;№ чека;Блюдо;Количество;Сумма;Кассир;После пречека;Причина\n"
    "05.10.2026;1001;Маргарита;1;580;таб. 11;да;гость передумал\n"
    "05.10.2026;1002;;;1160;таб. 12;нет;отмена заказа\n"
)
SALES_BY_CASHIER = "Дата;Блюдо;Кол-во;Сумма;Скидка;Официант\n01.10.2026;Маргарита;3;1500;240;Иванова\n"


def _rows(owner_engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with owner_engine.connect() as c:
        return [tuple(r) for r in c.execute(text(sql)).all()]


def test_stock_on_a_date_is_loaded_in_the_base_unit_and_replaced_on_reload(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    made = upload(client, hq, "stock_balances", STOCK, a1).json()
    assert made["status"] == "validated" and made["rows_valid"] == 2, made
    publish(client, hq, made["id"])
    assert sorted(float(str(q)) for (q,) in _rows(owner_engine, "SELECT qty FROM stock_balances")) == [
        9.0,
        12.5,
    ]
    # A corrected export of the same days replaces them.
    publish(client, hq, upload(client, hq, "stock_balances", STOCK.replace(";9;", ";8;"), a1).json()["id"])
    assert sorted(float(str(q)) for (q,) in _rows(owner_engine, "SELECT qty FROM stock_balances")) == [
        8.0,
        12.5,
    ]
    # The books' stock may be below zero (a document missing — M7 catches it): the file loads (review p. 5)
    minus = upload(client, hq, "stock_balances", STOCK.replace("12,5", "-1"), a1).json()
    assert minus["status"] != "failed" and not minus["errors"]


def test_voids_keep_the_cashier_and_whether_the_check_was_printed(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    made = upload(client, hq, "voids", VOIDS, a1).json()
    assert made["status"] == "validated" and made["rows_valid"] == 2, made
    publish(client, hq, made["id"])
    rows = _rows(
        owner_engine,
        "SELECT check_no, cashier, after_print, amount, menu_item_id IS NOT NULL"
        " FROM voids ORDER BY check_no",
    )
    assert [(r[0], r[2], float(str(r[3])), r[4]) for r in rows] == [
        ("1001", True, 580.0, True),
        ("1002", False, 1160.0, False),  # a whole check cancelled: no dish
    ]
    assert {r[1] for r in rows} == {"таб. 11", "таб. 12"}


def test_a_sale_keeps_its_cashier(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    publish(client, hq, upload(client, hq, "sales", SALES_BY_CASHIER, a1).json()["id"])
    (row,) = _rows(owner_engine, "SELECT cashier, discount FROM sales")
    assert str(row[0]).startswith("Кассир ") and row[1] == 240  # a name: kept as a code (docs/09)


def test_the_new_facts_stay_in_their_restaurant(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1, a2 = login(client, "admin@a.ru"), network.a.restaurants["A1"], network.a.restaurants["A2"]
    director2 = login(client, "director2@a.ru")
    assert upload(client, director2, "voids", VOIDS, a1).status_code in (403, 404)  # another restaurant's
    publish(client, hq, upload(client, hq, "voids", VOIDS, a1).json()["id"])
    publish(client, hq, upload(client, hq, "stock_balances", STOCK, a1).json()["id"])
    from app.core.db import RlsContext, apply_rls_context, get_sessionmaker

    with get_sessionmaker()() as s:
        apply_rls_context(
            s, RlsContext(network.a.id, network.a.users["director2@a.ru"], False, frozenset({a2}))
        )
        assert s.execute(text("SELECT count(*) FROM voids")).scalar_one() == 0
        assert s.execute(text("SELECT count(*) FROM stock_balances")).scalar_one() == 0
        apply_rls_context(s, RlsContext(network.b.id, network.b.users["admin@b.ru"], True, frozenset()))
        assert s.execute(text("SELECT count(*) FROM voids")).scalar_one() == 0


def test_a_cashiers_name_is_kept_as_a_stable_code_and_a_number_as_it_is() -> None:
    """docs/09, «Персональные данные» (Q26): no names of people stored; the same person keeps one code."""
    from app.imports.validate import cashier

    code = cashier("Иванова Е.")
    assert code is not None and code.startswith("Кассир ") and "Иванова" not in code
    assert cashier("иванова е.") == code and cashier("Петров С.") != code
    assert cashier("таб. 104") == "таб. 104" and cashier("17") == "17" and cashier("") is None
    assert cashier("№ 17") == "№ 17" and cashier("K12") == "K12"
    # a name with a number in it is still a name; another network, another code (review of stage 6.5, p. 12)
    assert cashier("Иванова Е. (12)", "A") is not None and "Иванова" not in (
        cashier("Иванова Е. (12)", "A") or ""
    )
    assert cashier("Иванова Е.", "A") != cashier("Иванова Е.", "B")
    assert len(cashier("x" * 300) or "") <= 100


def test_after_print_reads_the_tills_words() -> None:
    assert [after_print(w) for w in ("да", "Да", "после пречека", "напечатан", "1")] == [True] * 5
    assert [after_print(w) for w in ("нет", "", None, "до печати", "0")] == [False] * 5
    assert [after_print(w) for w in ("не напечатан", "не после печати", "Не после пречека")] == [False] * 3


def test_the_templates_describe_the_new_exports(client: TestClient, network: Network) -> None:
    names = {
        t["name"]: t for t in client.get("/api/imports/templates", headers=login(client, "admin@a.ru")).json()
    }
    assert (
        names["stock_balances"]["title"] == "Остатки на дату"
        and names["voids"]["title"] == "Удаления и отмены"
    )
    assert any(c["title"] == "Кассир" and not c["required"] for c in names["sales"]["columns"])
