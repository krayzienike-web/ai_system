import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import UUID

# Must be set before the application reads its settings.
os.environ.setdefault("FAI_ENV", "test")
os.environ.setdefault(
    "FAI_DATABASE_URL", "postgresql+psycopg://franchise_app:app@localhost:5432/franchise_test"
)
os.environ.setdefault(
    "FAI_MIGRATIONS_DATABASE_URL", "postgresql+psycopg://franchise_owner:owner@localhost:5432/franchise_test"
)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.main import app
from app.tenancy.models import Restaurant, Role, RoleAssignment, Tenant, User

PASSWORD = "secret-pass-1"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    url = get_settings().migrations_database_url
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db(owner_engine: Engine) -> None:
    with owner_engine.begin() as conn:
        conn.execute(text("TRUNCATE tenants CASCADE"))


@dataclass
class TenantData:
    id: UUID
    restaurants: dict[str, UUID] = field(default_factory=dict)  # code -> id
    users: dict[str, UUID] = field(default_factory=dict)  # email -> id


@dataclass
class Network:
    a: TenantData
    b: TenantData


def _make_tenant(session: Session, name: str, codes: list[str], prefix: str) -> TenantData:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    data = TenantData(id=tenant.id)

    def add_user(email: str, role: Role, restaurant_id: UUID | None = None) -> None:
        user = User(tenant_id=tenant.id, email=email, full_name=email, password_hash=hash_password(PASSWORD))
        session.add(user)
        session.flush()
        session.add(
            RoleAssignment(tenant_id=tenant.id, user_id=user.id, role=role, restaurant_id=restaurant_id)
        )
        data.users[email] = user.id

    add_user(f"admin@{prefix}.ru", Role.HQ_ADMIN)
    add_user(f"analyst@{prefix}.ru", Role.HQ_ANALYST)
    for i, code in enumerate(codes, start=1):
        restaurant = Restaurant(tenant_id=tenant.id, code=code, name=f"{name} {code}")
        session.add(restaurant)
        session.flush()
        data.restaurants[code] = restaurant.id
        add_user(f"director{i}@{prefix}.ru", Role.RESTAURANT_DIRECTOR, restaurant.id)
    session.flush()
    return data


@pytest.fixture
def network(owner_engine: Engine) -> Network:
    """Tenant A: 3 restaurants with a director each. Tenant B: 1 restaurant. Built as owner (no RLS)."""
    with Session(owner_engine) as session, session.begin():
        a = _make_tenant(session, "Сеть А", ["A1", "A2", "A3"], "a")
        b = _make_tenant(session, "Сеть Б", ["B1"], "b")
    return Network(a=a, b=b)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
