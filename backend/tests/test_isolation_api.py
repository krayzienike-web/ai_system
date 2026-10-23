"""Data isolation through the API: directors see only their restaurant, tenants never see each other."""

from fastapi.testclient import TestClient

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
