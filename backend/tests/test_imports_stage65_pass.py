"""Stage 6.5 exports (docs/09), the end-of-stage pass: a books' stock below zero is stored as it is, a
corrected «Удаления и отмены» of the same days replaces the first, another network sees none of the new
facts (TC-IMP-25)."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.db import RlsContext, apply_rls_context, get_sessionmaker
from tests.conftest import Network, login
from tests.test_imports_api import _pin_today, publish, upload  # noqa: F401  (a fixture)
from tests.test_imports_api import catalog as catalog
from tests.test_imports_stage65 import STOCK, VOIDS


def _rows(owner_engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with owner_engine.connect() as c:
        return [tuple(r) for r in c.execute(text(sql)).all()]


def test_a_stock_below_zero_is_published_as_it_is(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    made = upload(client, hq, "stock_balances", STOCK.replace("12,5", "-1,5"), a1).json()
    assert made["status"] == "validated" and made["rows_valid"] == 2, made
    publish(client, hq, made["id"])
    # the minus is kept (M7 tells of the missing document; M6 reads it as nothing on the shelf)
    assert sorted(Decimal(str(q)) for (q,) in _rows(owner_engine, "SELECT qty FROM stock_balances")) == [
        Decimal("-1.5"),
        9,
    ]


def test_voids_of_the_same_days_published_again_replace_the_first(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    publish(client, hq, upload(client, hq, "voids", VOIDS, a1).json()["id"])
    assert upload(client, hq, "voids", VOIDS, a1).status_code >= 400  # the very same file: a duplicate
    # a corrected export of the same days replaces them, nothing is added
    publish(client, hq, upload(client, hq, "voids", VOIDS.replace(";580;", ";600;"), a1).json()["id"])
    rows = _rows(owner_engine, "SELECT check_no, amount FROM voids ORDER BY check_no")
    assert rows == [("1001", Decimal("600.00")), ("1002", Decimal("1160.00"))]


def test_another_network_sees_no_stock_and_no_voids(
    client: TestClient, network: Network, catalog: None, owner_engine: Engine
) -> None:
    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    publish(client, hq, upload(client, hq, "voids", VOIDS, a1).json()["id"])
    publish(client, hq, upload(client, hq, "stock_balances", STOCK, a1).json()["id"])
    with get_sessionmaker()() as s:
        apply_rls_context(s, RlsContext(network.b.id, network.b.users["admin@b.ru"], True, frozenset()))
        assert s.execute(text("SELECT count(*) FROM stock_balances")).scalar_one() == 0
        assert s.execute(text("SELECT count(*) FROM voids")).scalar_one() == 0
        # and a file for network A's restaurant cannot be uploaded from network B
    other = upload(client, login(client, "admin@b.ru"), "voids", VOIDS, a1)
    assert other.status_code in (403, 404, 422)
    assert len(_rows(owner_engine, "SELECT 1 FROM voids")) == 2
