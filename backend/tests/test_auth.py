from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.security import create_token
from tests.conftest import Network, login


def test_health(client: TestClient, network: Network) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_me_for_director(client: TestClient, network: Network) -> None:
    headers = login(client, "director1@a.ru")
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["role"] == "restaurant_director"
    assert me["restaurant"]["id"] == str(network.a.restaurants["A1"])
    assert "tasks.execute" in me["permissions"]
    assert "restaurants.manage" not in me["permissions"]


def test_login_is_case_insensitive_on_email(client: TestClient, network: Network) -> None:
    login(client, "Admin@A.ru")


def test_wrong_password_and_unknown_email_look_the_same(client: TestClient, network: Network) -> None:
    wrong = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": "nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@a.ru", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_inactive_user_cannot_login_and_token_stops_working(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    headers = login(client, "director1@a.ru")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false WHERE email = 'director1@a.ru'"))
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    response = client.post("/api/auth/login", json={"email": "director1@a.ru", "password": "secret-pass-1"})
    assert response.status_code == 401


def test_refresh_flow(client: TestClient, network: Network) -> None:
    tokens = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": "secret-pass-1"}).json()
    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"})
    assert me.json()["role"] == "hq_admin"


def test_access_token_is_not_a_refresh_token(client: TestClient, network: Network) -> None:
    tokens = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": "secret-pass-1"}).json()
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    bad = {"Authorization": f"Bearer {tokens['refresh_token']}"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


def test_missing_or_garbage_token(client: TestClient, network: Network) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_token_with_foreign_tenant_claim_is_rejected(client: TestClient, network: Network) -> None:
    # A user id paired with another tenant id: RLS hides the user, so the context cannot be built.
    forged = create_token(network.a.users["admin@a.ru"], network.b.id, "access")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_login_is_audited(client: TestClient, network: Network, owner_engine: Engine) -> None:
    login(client, "admin@a.ru")
    with owner_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'auth.login'")).scalar_one()
    assert count == 1
