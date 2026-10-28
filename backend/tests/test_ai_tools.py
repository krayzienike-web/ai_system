"""The assistant's tools on the demo network (docs/08; CLAUDE.md, principle 2: every chat tool has an
isolation test). The registry is walked, so a new tool without sample arguments here fails the suite."""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.ai import tools
from app.catalog.models import Product
from app.insights.models import Finding
from app.operations.models import Receipt
from app.overview.models import KpiSnapshot
from app.tenancy.context import tool_session
from app.tenancy.models import Restaurant, User
from tests.conftest import Network
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


class World:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        with Session(owner_engine) as s:
            self.places = {
                r.code: r
                for r in s.execute(select(Restaurant).where(Restaurant.tenant_id == network.a.id)).scalars()
            }
            r01, r02 = self.places["R01"].id, self.places["R02"].id
            open_ = Finding.status != "dismissed"
            visible = Finding.review_status.is_(None) | (Finding.review_status == "confirmed")
            self.own = s.execute(
                select(Finding.id).where(Finding.restaurant_id == r01, open_, visible)
            ).scalar()
            self.other = s.execute(
                select(Finding.id).where(Finding.restaurant_id == r02, open_, visible)
            ).scalar()
            self.director = s.execute(select(User.id).where(User.email == "r01@a.ru")).scalar_one()
        self.tenants = {"director": network.a.id, "admin": network.a.id, "foreign": network.b.id}
        self.users = {
            "director": self.director,
            "admin": network.a.users["admin@a.ru"],
            "foreign": network.b.users["admin@b.ru"],
        }

    def call(self, who: str, name: str, args: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
        return tools.run(name, args or {}, user_id=self.users[who], tenant_id=self.tenants[who], today=TODAY)


@pytest.fixture
def world(network: Network, owner_engine: Engine, demo: dict[str, UUID]) -> World:  # noqa: F811
    return World(network, owner_engine)


def samples(w: World) -> dict[str, list[dict[str, Any]]]:
    """Arguments every tool is walked with: one call each, and the ones that name another restaurant."""
    return {
        "get_kpis": [{}],
        "get_findings": [{}, {"process": "production"}, {"restaurant_code": "R02"}],
        "explain_finding": [{"finding_id": str(w.own)}, {"finding_id": str(w.other)}],
        "compare_restaurants": [{}],
        "get_tasks": [{}],
        "get_checks": [{}],
        "search_products": [{"query": "ло"}],
        "get_purchase_prices": [{"product": "ло", "days": 180}],
    }


def test_every_tool_has_sample_arguments_and_a_schema_the_api_accepts(world: World) -> None:
    assert set(samples(world)) == set(tools.TOOLS)
    for t in tools.TOOLS.values():
        schema = t.schema()
        assert schema["input_schema"]["type"] == "object"
        assert schema["input_schema"]["additionalProperties"] is False
        assert t.description and len(t.name) <= 64


def test_a_director_never_sees_another_restaurant_and_another_network_sees_nothing(world: World) -> None:
    others = [r for code, r in world.places.items() if code != "R01"]
    markers = [m for r in others for m in (str(r.id), r.name)] + [str(world.other)]
    network_markers = [m for r in world.places.values() for m in (str(r.id), r.name)]
    network_markers += [str(world.own), str(world.other)]
    leaks = []
    for name, calls in samples(world).items():
        for args in calls:
            result, _ = world.call("director", name, args)
            body = json.dumps(result, ensure_ascii=False)
            leaks += [f"director: {name}({args}) shows {m}" for m in markers if m in body]
            result, _ = world.call("foreign", name, args)
            body = json.dumps(result, ensure_ascii=False)
            leaks += [f"network B: {name}({args}) shows {m}" for m in network_markers if m in body]
    assert leaks == [], leaks


def test_comparing_restaurants_is_only_for_hq(world: World) -> None:
    result, error = world.call("director", "compare_restaurants")
    assert error and result == {"error": "Эти данные пользователю недоступны"}
    with tool_session(world.director, world.tenants["director"]) as (_, ctx):
        assert "compare_restaurants" not in [s["name"] for s in tools.schemas(ctx)]
    result, error = world.call("admin", "compare_restaurants")
    assert not error and {r["code"] for r in result["restaurants"]} == set(world.places)


def test_a_finding_of_another_restaurant_or_under_review_is_not_explained(
    world: World, owner_engine: Engine
) -> None:
    assert world.call("director", "explain_finding", {"finding_id": str(world.other)})[0] == {
        "error": "Находка не найдена или недоступна"
    }
    own, error = world.call("director", "explain_finding", {"finding_id": str(world.own)})
    assert not error and own["id"] == str(world.own) and own["restaurant"] == world.places["R01"].name
    with Session(owner_engine) as s:
        pending = s.execute(select(Finding.id).where(Finding.review_status == "pending")).scalar()
    assert pending is not None  # the demo leaves today's M6/M7 findings waiting for review
    assert world.call("admin", "explain_finding", {"finding_id": str(pending)})[1]


def test_kpis_are_the_engines_figures_formatted_and_the_director_gets_the_network_average(
    world: World, owner_engine: Engine
) -> None:
    result, _ = world.call("director", "get_kpis")
    assert [r["code"] for r in result["restaurants"]] == ["R01"]
    with Session(owner_engine) as s:
        mine = s.execute(
            select(KpiSnapshot).where(KpiSnapshot.restaurant_id == world.places["R01"].id)
        ).scalar()
        net = s.execute(
            select(KpiSnapshot).where(
                KpiSnapshot.restaurant_id.is_(None), KpiSnapshot.tenant_id == world.tenants["admin"]
            )
        ).scalar()
    assert mine is not None and net is not None
    assert result["restaurants"][0]["food_cost_actual"] == tools.pct(mine.food_cost_actual)
    assert result["network_average"]["food_cost_actual"] == tools.pct(net.food_cost_actual)
    assert result["network_average"]["revenue"] == tools.money(net.revenue)


def test_findings_are_the_screens_open_findings(world: World, client: Any) -> None:
    from tests.conftest import login

    result, _ = world.call("director", "get_findings")
    screen = client.get("/api/findings", headers=login(client, "r01@a.ru")).json()
    open_ids = {f["id"] for f in screen if f["status"] in ("new", "in_work", "in_experiment")}
    assert {f["id"] for f in result["findings"]} <= open_ids and result["total"] == len(open_ids)
    production, _ = world.call("admin", "get_findings", {"process": "production"})
    assert production["findings"] and {f["process"] for f in production["findings"]} == {"Производство (ТТК)"}
    assert world.call("admin", "get_findings", {"restaurant_code": "ZZZ"})[1]


def test_purchase_prices_are_amount_over_quantity_from_the_invoices(
    world: World, owner_engine: Engine
) -> None:
    result, _ = world.call("director", "get_purchase_prices", {"product": "ло", "days": 180})
    assert result["prices"] and {p["restaurant"] for p in result["prices"]} == {world.places["R01"].name}
    first = result["prices"][0]
    with Session(owner_engine) as s:
        amount, qty = s.execute(
            select(func.sum(Receipt.amount), func.sum(Receipt.qty))
            .join(Product, Product.id == Receipt.product_id)
            .where(
                Product.name == first["product"],
                Receipt.restaurant_id == world.places["R01"].id,
                Receipt.day > TODAY.replace(month=4, day=23),
            )
        ).one()
    assert first["amount"] == tools.money(Decimal(amount))
    assert first["avg_price_per_unit"].startswith(tools.price(Decimal(amount) / Decimal(qty)))


def test_bad_arguments_unknown_tools_and_unknown_users_are_answers_not_crashes(world: World) -> None:
    result, error = world.call("admin", "get_purchase_prices", {"product": "x", "days": 1000, "sql": "drop"})
    assert error and result["error"] == "Неверные аргументы"
    assert world.call("admin", "explain_finding", {"finding_id": "not-a-uuid"})[1]
    assert world.call("admin", "drop_tables") == ({"error": "Нет инструмента drop_tables"}, True)
    gone = tools.run("get_kpis", {}, user_id=UUID(int=7), tenant_id=world.tenants["admin"], today=TODAY)
    assert gone == ({"error": "Пользователь не найден или отключен"}, True)


def test_search_escapes_like_wildcards(world: World) -> None:
    assert world.call("admin", "search_products", {"query": "%%"})[0] == {"products": []}
    found, _ = world.call("admin", "search_products", {"query": "ло"})
    assert found["products"] and all("ло" in p["name"].lower() for p in found["products"])
