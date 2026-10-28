"""Data isolation through the API: directors see only their restaurant, tenants never see each other."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.insights.models import Finding
from tests.conftest import Network, login


def _codes(client: TestClient, headers: dict[str, str]) -> list[str]:
    response = client.get("/api/restaurants", headers=headers)
    assert response.status_code == 200
    return [r["code"] for r in response.json()]


def test_hq_sees_all_restaurants_of_own_tenant_only(client: TestClient, network: Network) -> None:
    assert _codes(client, login(client, "admin@a.ru")) == ["A1", "A2", "A3"]
    assert _codes(client, login(client, "analyst@a.ru")) == ["A1", "A2", "A3"]
    assert _codes(client, login(client, "admin@b.ru")) == ["B1"]


def test_director_sees_only_own_restaurant(client: TestClient, network: Network) -> None:
    assert _codes(client, login(client, "director2@a.ru")) == ["A2"]


def test_director_cannot_open_other_restaurant(client: TestClient, network: Network) -> None:
    headers = login(client, "director1@a.ru")
    own = client.get(f"/api/restaurants/{network.a.restaurants['A1']}", headers=headers)
    other = client.get(f"/api/restaurants/{network.a.restaurants['A2']}", headers=headers)
    foreign = client.get(f"/api/restaurants/{network.b.restaurants['B1']}", headers=headers)
    assert own.status_code == 200
    assert other.status_code == foreign.status_code == 404


def test_hq_cannot_open_restaurant_of_another_tenant(client: TestClient, network: Network) -> None:
    headers = login(client, "admin@a.ru")
    assert client.get(f"/api/restaurants/{network.b.restaurants['B1']}", headers=headers).status_code == 404


def test_only_hq_admin_manages_restaurants(client: TestClient, network: Network) -> None:
    body = {"code": "A4", "name": "Новая точка"}
    assert (
        client.post("/api/restaurants", json=body, headers=login(client, "director1@a.ru")).status_code == 403
    )
    assert (
        client.post("/api/restaurants", json=body, headers=login(client, "analyst@a.ru")).status_code == 403
    )
    created = client.post("/api/restaurants", json=body, headers=login(client, "admin@a.ru"))
    assert created.status_code == 201
    duplicate = client.post("/api/restaurants", json=body, headers=login(client, "admin@a.ru"))
    assert duplicate.status_code == 409


def test_same_restaurant_code_allowed_in_other_tenant(client: TestClient, network: Network) -> None:
    body = {"code": "A1", "name": "Совпадающий код"}
    assert client.post("/api/restaurants", json=body, headers=login(client, "admin@b.ru")).status_code == 201


def test_users_management_is_hq_admin_only(client: TestClient, network: Network) -> None:
    assert client.get("/api/users", headers=login(client, "director1@a.ru")).status_code == 403
    assert client.get("/api/users", headers=login(client, "analyst@a.ru")).status_code == 403
    emails = [u["email"] for u in client.get("/api/users", headers=login(client, "admin@a.ru")).json()]
    assert len(emails) == 5
    assert all(e.endswith("@a.ru") for e in emails)


def test_admin_creates_director_who_sees_only_their_restaurant(client: TestClient, network: Network) -> None:
    admin = login(client, "admin@a.ru")
    response = client.post(
        "/api/users",
        headers=admin,
        json={
            "email": "new.director@a.ru",
            "full_name": "Новый директор",
            "password": "long-password",
            "role": "restaurant_director",
            "restaurant_id": str(network.a.restaurants["A3"]),
        },
    )
    assert response.status_code == 201, response.text
    assert _codes(client, login(client, "new.director@a.ru", "long-password")) == ["A3"]


def test_director_needs_exactly_one_visible_restaurant(client: TestClient, network: Network) -> None:
    admin = login(client, "admin@a.ru")
    base = {"full_name": "X", "password": "long-password", "role": "restaurant_director"}
    no_restaurant = client.post("/api/users", headers=admin, json={**base, "email": "x1@a.ru"})
    foreign_restaurant = client.post(
        "/api/users",
        headers=admin,
        json={**base, "email": "x2@a.ru", "restaurant_id": str(network.b.restaurants["B1"])},
    )
    hq_with_restaurant = client.post(
        "/api/users",
        headers=admin,
        json={
            **base,
            "email": "x3@a.ru",
            "role": "hq_analyst",
            "restaurant_id": str(network.a.restaurants["A1"]),
        },
    )
    assert no_restaurant.status_code == 422
    assert foreign_restaurant.status_code == 422
    assert hq_with_restaurant.status_code == 422


def test_email_of_another_tenant_is_rejected(client: TestClient, network: Network) -> None:
    response = client.post(
        "/api/users",
        headers=login(client, "admin@a.ru"),
        json={"email": "admin@b.ru", "full_name": "X", "password": "long-password", "role": "hq_analyst"},
    )
    assert response.status_code == 409


def test_engine_findings_and_settings_stay_within_the_tenant(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """Review, verification and engine parameters of one network are invisible to another."""
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        pending = Finding(
            tenant_id=network.a.id,
            restaurant_id=network.a.restaurants["A1"],
            kind="problem",
            process="production",
            title="Перерасход по техкарте",
            effect_rub_month=Decimal(5000),
            actions=[],
            found_on=date(2026, 10, 1),
            key="M1:A1:P01",
            module="M1",
            review_status="pending",
        )
        s.add(pending)
    foreign = login(client, "admin@b.ru")
    for path in (f"/api/findings/{pending.id}", f"/api/findings/{pending.id}/verification"):
        assert client.get(path, headers=foreign).status_code == 404
    review = client.post(f"/api/findings/{pending.id}/review", headers=foreign, json={"verdict": "confirm"})
    assert review.status_code == 404
    assert client.get("/api/findings", headers=foreign, params={"review": "pending"}).json() == []
    # A director of the same network does not see it either while it waits for the check.
    director = login(client, "director1@a.ru")
    assert client.get(f"/api/findings/{pending.id}", headers=director).status_code == 404

    # Engine parameters: tenant B's change does not touch tenant A.
    assert (
        client.put("/api/settings/engine", headers=foreign, json={"values": {"M3_OVERPAY": 10}}).status_code
        == 200
    )
    mine = {
        p["key"]: p for p in client.get("/api/settings/engine", headers=login(client, "admin@a.ru")).json()
    }
    assert mine["M3_OVERPAY"]["value"] == mine["M3_OVERPAY"]["default"]
    assert (
        client.put("/api/settings/engine", headers=director, json={"values": {"M3_OVERPAY": 10}}).status_code
        == 403
    )


def test_stage_4_endpoints_stay_within_the_restaurant_and_the_network(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """Stage 4 (CLAUDE.md, principle 2): «Откуда цифры» (`/findings/{id}/sources`), «Сеть» with its matrix and
    overpayment (`/overview/network`), and the recalculation button (`POST /analytics/run`) — for another
    restaurant's director and for another network."""

    def purchasing(restaurant: UUID | None, key: str, effect: str, review: str = "confirmed") -> Finding:
        return Finding(
            tenant_id=network.a.id,
            restaurant_id=restaurant,
            kind="problem",
            process="purchasing",
            title=f"Переплата {key}",
            effect_rub_month=Decimal(effect),
            actions=[],
            found_on=date(2026, 10, 1),
            key=key,
            module="M3",
            status="new",
            review_status=review,
        )

    a1 = network.a.restaurants["A1"]
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        own = purchasing(a1, "M3:A1:P1", "7000.00")
        net_wide = purchasing(None, "M3:net:P1:growth", "3000.00")
        pending = purchasing(a1, "M3:A1:P2", "5000.00", review="pending")
        s.add_all([own, net_wide, pending])
    hq, analyst = login(client, "admin@a.ru"), login(client, "analyst@a.ru")
    director1, director2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    foreign = login(client, "admin@b.ru")

    def sources(finding: Finding, headers: dict[str, str]) -> int:
        code: int = client.get(f"/api/findings/{finding.id}/sources", headers=headers).status_code
        return code

    # «Откуда цифры» follows the card: own checked finding only; not another restaurant, not the network's
    # finding, not one waiting for the check, never another network.
    assert [sources(own, h) for h in (hq, director1, director2, foreign)] == [200, 200, 404, 404]
    assert [sources(net_wide, h) for h in (hq, director1, foreign)] == [200, 404, 404]
    assert [sources(pending, h) for h in (hq, director1, foreign)] == [200, 404, 404]

    # «Сеть»: HQ only; the matrix and the overpayment are the network's own checked open problems.
    assert client.get("/api/overview/network", headers=director1).status_code == 403
    assert client.get("/api/overview/network", headers=analyst).status_code == 200
    mine = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()
    # 7000.00 (A1) + 3000.00 (the whole network) = 10000.00; the pending 5000.00 is not counted yet.
    assert Decimal(mine["overpay"]) == Decimal("10000.00")
    cells = {(r["code"], c["process"]): Decimal(c["losses"]) for r in mine["matrix"] for c in r["cells"]}
    assert cells[("A1", "purchasing")] == Decimal(
        "7000.00"
    )  # the network's finding is in no restaurant's row
    assert {r["code"] for r in mine["matrix"]} == {"A1", "A2", "A3"}
    theirs = client.get("/api/overview/network", headers=foreign, params={"preset": "4w"})
    assert [r["code"] for r in theirs.json()["matrix"]] == ["B1"]
    assert Decimal(theirs.json()["overpay"]) == Decimal(0)
    assert "Сеть А" not in theirs.text and "Переплата" not in theirs.text

    # The button: HQ admin only; another network's run does not touch this network's runs or findings.
    for headers in (director1, analyst):
        assert client.post("/api/analytics/run", headers=headers).status_code == 403
    assert client.post("/api/analytics/run", headers=foreign).status_code == 202
    assert client.get("/api/analytics/runs/latest", headers=foreign).json()["trigger"] == "manual"
    assert client.get("/api/analytics/runs/latest", headers=hq).json() is None
    with owner_engine.connect() as c:
        left = c.execute(
            text("SELECT count(*) FROM findings WHERE tenant_id = :t"), {"t": network.a.id}
        ).scalar_one()
    assert left == 3
