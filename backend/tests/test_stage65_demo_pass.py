"""Stage 6.5 on the demo network, after the code review (TC-ENG-30, TC-ENG-44): a re-run gives the same
keys and the same numbers, the check of every new kind agrees with the engine — and disagrees once the rows
change — and a director meets a data finding's points only with the finding."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.core.period import get_today
from app.core.security import hash_password
from app.insights.models import Finding
from app.main import app
from app.operations.models import StockBalance, Void
from app.overview.models import KpiSnapshot
from app.tenancy.models import Restaurant, Role, RoleAssignment, User
from tests.conftest import PASSWORD, Network, hq_task, login
from tests.test_analytics import demo  # noqa: F401  (the demo network in tenant A)

NEW_KINDS = {
    "M2": ("plowhorse", "puzzle"),
    "M3": ("jump",),
    "M6": ("overstock",),
    "M7": ("prices", "partial"),
}


def _state(
    owner_engine: Engine, tenant: UUID
) -> tuple[dict[str, tuple[Any, ...]], dict[Any, tuple[Any, ...]]]:
    with Session(owner_engine) as s:
        findings = {
            f.key: (f.effect_rub_month, f.evidence, f.story_key, f.story_title, f.confidence, f.title)
            for f in s.execute(select(Finding).where(Finding.tenant_id == tenant)).scalars()
            if f.key
        }
        kpis = {
            k.restaurant_id: (k.data_quality, k.data_quality_parts)
            for k in s.execute(select(KpiSnapshot).where(KpiSnapshot.tenant_id == tenant)).scalars()
        }
    return findings, kpis


def _check(client: TestClient, headers: dict[str, str], finding_id: str) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/api/findings/{finding_id}/verification", headers=headers).json()
    return body


def _director(owner_engine: Engine, network: Network, code: str) -> str:
    email = f"{code.lower()}@a.ru"
    with Session(owner_engine) as s, s.begin():
        restaurant = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == code)
        ).scalar_one()
        user = User(
            tenant_id=network.a.id, email=email, full_name=code, password_hash=hash_password(PASSWORD)
        )
        s.add(user)
        s.flush()
        s.add(
            RoleAssignment(
                tenant_id=network.a.id,
                user_id=user.id,
                role=Role.RESTAURANT_DIRECTOR,
                restaurant_id=restaurant,
            )
        )
    return email


def test_stage_six_five_on_the_demo_network_after_the_review(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
    owner_engine: Engine,
) -> None:
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 20)
    try:
        hq, analyst = login(client, "admin@a.ru"), login(client, "analyst@a.ru")

        # 1. Idempotent: a second run on the same data gives the same keys and the same numbers — the
        #    findings, their stories and the data quality scores (CLAUDE.md, principle 4).
        client.post("/api/analytics/run", headers=hq)
        first = _state(owner_engine, network.a.id)
        client.post("/api/analytics/run", headers=hq)
        again = _state(owner_engine, network.a.id)
        assert set(first[0]) == set(again[0]) and first == again
        new = [
            k
            for k, v in first[0].items()
            if k.split(":")[0] in NEW_KINDS and v[1].get("kind") in NEW_KINDS[k.split(":")[0]]
        ]
        assert len(new) >= 9  # all the planted findings of the new kinds are among them
        assert all(dq is not None and 0 <= dq <= 100 for dq, _ in first[1].values())

        pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
        by = {(f["restaurant_code"], f["title"]): f for f in pending}

        # 2. The one planted overstock the demo test does not recompute: rucola R01 agrees with its check.
        rucola = by[("R01", "Затоваривание: Руккола")]
        v = _check(client, analyst, rucola["id"])
        assert (
            v["supported"] and all(c["ok"] for c in v["checks"]) and all(r["passed"] for r in v["rules"])
        ), v

        # 3. The check recomputes from the rows, not from the finding: changed rows → a failed check.
        cream = by[("R06", "Затоваривание: Сливки 33%")]
        cashier = next(f for (code, title), f in by.items() if code == "R08" and title.endswith("таб. 103"))
        assert all(c["ok"] for c in _check(client, analyst, cream["id"])["checks"])
        assert all(c["ok"] for c in _check(client, analyst, cashier["id"])["checks"])
        with Session(owner_engine) as s, s.begin():
            r06, r08 = (
                s.execute(
                    select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == c)
                ).scalar_one()
                for c in ("R06", "R08")
            )
            p04 = s.execute(
                select(Product.id).where(Product.tenant_id == network.a.id, Product.name == "Сливки 33%")
            ).scalar_one()
            s.execute(
                update(StockBalance)
                .where(StockBalance.restaurant_id == r06, StockBalance.product_id == p04)
                .values(qty=StockBalance.qty + 5)
            )
            s.execute(  # one ruble more on each of the cashier's removals after printing
                update(Void)
                .where(Void.restaurant_id == r08, Void.cashier == "таб. 103", Void.after_print.is_(True))
                .values(amount=Void.amount + Decimal(1))
            )
        failed = {c["check"] for c in _check(client, analyst, cream["id"])["checks"] if not c["ok"]}
        assert "Медиана остатков совпадает с тем, что посчитал движок" in failed
        failed = {c["check"] for c in _check(client, analyst, cashier["id"])["checks"] if not c["ok"]}
        assert "Сумма удалений совпадает с тем, что посчитал движок" in failed

        # 4. R03's director: the 5 points for the odd invoice price only once HQ checked it and gave a task.
        r03 = login(client, _director(owner_engine, network, "R03"))

        def week(headers: dict[str, str]) -> dict[str, Any]:
            kpi: dict[str, Any] = client.get("/api/overview/restaurants/R03", headers=headers).json()["kpi"]
            return kpi

        part = {"label": "Ошибочные цены в накладных", "points": 5}
        assert part in week(hq)["data_quality_parts"] and part not in week(r03)["data_quality_parts"]
        odd = by[("R03", "Цены в накладных похожи на ошибку: 1 строка")]
        client.post(f"/api/findings/{odd['id']}/review", headers=analyst, json={"verdict": "confirm"})
        hq_task(owner_engine, UUID(odd["id"]))
        mine = week(r03)
        assert part in mine["data_quality_parts"]
        assert mine["data_quality"] == 100 - sum(p["points"] for p in mine["data_quality_parts"])
        # the network's no-recipe finding stays the HQ's: no word of it to the director
        assert all(p["label"] != "Продается блюдо без техкарты" for p in mine["data_quality_parts"])
        # nothing of another restaurant through the overview, the stories or the check
        assert client.get("/api/overview/restaurants/R06", headers=r03).status_code == 404
        members = [
            m
            for f in client.get("/api/findings", headers=r03).json()
            if f["story"]
            for m in f["story"]["findings"]
        ]
        assert all(m["restaurant_code"] == "R03" for m in members)
        assert client.get(f"/api/findings/{cream['id']}/verification", headers=r03).status_code == 403
    finally:
        app.dependency_overrides.pop(get_today, None)
