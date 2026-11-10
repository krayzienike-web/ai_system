"""The test kit of the stand (stage 8, docs/15): Excel files shaped like real exports, loaded by hand into
«Тестовая сеть». The test goes the way a person goes through «Данные»: no template chosen, the file says what
it is; 1С names matched once; the broken files show their rows; the engine finds the planted problems."""

from collections.abc import Iterator
from pathlib import Path
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import cli
from app.analytics import engine, runs
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.demo import test_kit
from app.insights.models import Finding
from app.main import app
from app.tenancy.context import load_access_context
from app.tenancy.models import Restaurant, Tenant, User
from tests.conftest import login

TODAY = date(2026, 10, 20)  # the stand's day (DEMO_TODAY)
PASSWORD = "test-pass-1"


@pytest.fixture
def kit() -> test_kit.Kit:
    return test_kit.build()


@pytest.fixture
def stand(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    monkeypatch.setattr(runs, "dispatch", lambda *a, **k: None)  # one engine run at the end, not per file
    yield
    app.dependency_overrides.pop(get_today, None)


def _upload(client: TestClient, auth: dict[str, str], path: str, raw: bytes, restaurant: str | None) -> Any:
    data = {"restaurant_id": restaurant} if restaurant else {}
    r = client.post("/api/imports", headers=auth, files={"file": (path.split("/")[-1], raw)}, data=data)
    assert r.status_code == 201, (path, r.text)
    return r.json()


def test_the_kit_is_the_same_every_time(kit: test_kit.Kit) -> None:
    again = test_kit.build()
    assert kit.files == again.files
    assert len(kit.order) == 5 + 6 * 3
    assert len(kit.erp_names) == 5


def test_the_test_network_loads_by_hand_and_the_engine_finds_its_problems(
    kit: test_kit.Kit, stand: None, client: TestClient, owner_engine: Engine
) -> None:
    """TC-DEMO-09: every file loads without a template; TC-DEMO-10: the broken ones say which rows."""
    cli.seed_test_network(PASSWORD, reset=False)
    with Session(owner_engine) as s:
        ids = {r.code: str(r.id) for r in s.execute(select(Restaurant)).scalars()}
    auth = login(client, "admin@test.local", PASSWORD)
    for path, code in kit.order:
        batch = _upload(client, auth, path, kit.files[path], ids[code] if code else None)
        assert batch["errors"] == [], (path, batch["errors"][:3])
        if batch["status"] == "needs_matching":
            assert code == test_kit.ERP_RESTAURANT and batch["template"] == "receipts"
            names = {u["name"] for u in batch["unmatched"]}
            assert names == set(kit.erp_names)  # only 1С's own names; suppliers by name, grams converted
            by_code = {o["code"]: o["id"] for o in client.get("/api/catalog/product", headers=auth).json()}
            matches = [
                {"kind": u["kind"], "key": u["key"], "target_id": by_code[kit.erp_names[u["name"]]]}
                for u in batch["unmatched"]
            ]
            r = client.post(f"/api/imports/{batch['id']}/match", headers=auth, json={"matches": matches})
            batch = r.json()
        assert batch["status"] == "validated", (path, batch["status"])
        r = client.post(f"/api/imports/{batch['id']}/publish", headers=auth)
        assert r.status_code == 200, (path, r.text)

    broken = {p: b for p, b in kit.files.items() if p.startswith(test_kit.BROKEN)}
    sales, receipts = sorted(broken, reverse=True)
    batch = _upload(client, auth, sales, broken[sales], ids["R02"])
    assert batch["status"] == "failed" and sorted(e["row"] for e in batch["errors"]) == [9, 16, 30]
    batch = _upload(client, auth, receipts, broken[receipts], ids["R01"])
    assert batch["status"] == "failed" and "упак" in batch["errors"][0]["message"]

    freshness = client.get("/api/imports/freshness", headers=auth).json()
    assert freshness, "every restaurant shows by what day its data goes"

    with Session(owner_engine) as s:
        admin = s.execute(select(User).where(User.email == "admin@test.local")).scalar_one()
        user_id, tenant_id = admin.id, admin.tenant_id
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, user_id, tenant_id)
        assert ctx is not None
        engine.run(session, ctx, TODAY)
        session.commit()
    with Session(owner_engine) as s:
        found = {
            (f.module, (f.evidence or {}).get("product"))
            for f in s.execute(select(Finding).where(Finding.tenant_id == tenant_id)).scalars()
        }
    assert ("M1", "P01") in found  # R01: mozzarella over the recipe
    assert ("M1", "P09") in found  # R03: salmon yield
    assert ("M5", "P10") in found  # R01: rocket written off


def test_the_nightly_demo_reset_keeps_the_test_network(owner_engine: Engine) -> None:
    """TC-DEMO-11: reset-demo rebuilds only the demo; seed-test-network --reset empties the test network."""
    cli.seed_test_network(PASSWORD, reset=False)
    cli.seed_test_network(PASSWORD, reset=False)  # a second time changes nothing
    cli.reset_demo("demo-pass-1", 42)
    with Session(owner_engine) as s:
        assert sorted(s.execute(select(Tenant.name)).scalars()) == sorted(
            [cli.DEMO_TENANT, test_kit.TEST_TENANT]
        )
        test_id = s.execute(select(Tenant.id).where(Tenant.name == test_kit.TEST_TENANT)).scalar_one()
        assert (
            s.execute(select(func.count()).select_from(User).where(User.tenant_id == test_id)).scalar_one()
            == 5
        )
    cli.seed_test_network(PASSWORD, reset=True)
    with Session(owner_engine) as s:
        assert s.execute(select(Tenant.id).where(Tenant.name == test_kit.TEST_TENANT)).scalar_one() != test_id
        assert s.execute(select(Tenant.name).where(Tenant.name == cli.DEMO_TENANT)).scalar_one()


def test_the_kit_in_the_repository_is_the_kit_the_code_builds(kit: test_kit.Kit) -> None:
    """deploy/test-kit is what `generate-test-kit` writes: regenerate it after changing the generator."""
    folder = Path(__file__).resolve().parents[2] / "deploy" / "test-kit"
    on_disk = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*.xlsx")}
    assert on_disk == kit.files
