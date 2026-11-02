"""The analyst's pre-check (ADR 0008, stage 5.5): what to look at is computed by the code, the draft
verdict is the model's, the analyst decides, and how often they agreed is counted."""

import json
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.ai import precheck
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.insights.models import Finding
from app.main import app
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _key(owner_engine: Engine, network: Network, key: str) -> UUID:
    with Session(owner_engine) as s:
        return s.execute(
            select(Finding.id).where(Finding.tenant_id == network.a.id, Finding.key == key)
        ).scalar_one()


def draft(verdict: str, reason: str | None = None, *, rationale: str = "По фактам") -> Any:
    def reply(_: ModelRequest) -> Reply:
        body = {"verdict": verdict, "reason": reason, "rationale": rationale, "look_at": ["Накладные"]}
        return text_reply(json.dumps(body, ensure_ascii=False))

    return reply


@pytest.mark.usefixtures("demo")
def test_what_to_look_at_is_computed_by_the_code(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """R10's mozzarella runs below the recipe because two invoices are missing: the pre-check points at the
    data problem of the same restaurant."""
    admin = login(client, "admin@a.ru")
    r10 = client.get(
        f"/api/findings/{_key(owner_engine, network, 'M1:R10:P01:under')}/precheck", headers=admin
    ).json()
    data = next(f for f in r10["flags"] if f["code"] == "data_problems")
    assert r10["draft"] is None and "Моцарелла" in data["note"]  # M7: the stock by documents goes negative


@pytest.mark.usefixtures("demo")
def test_holidays_spikes_and_short_periods_are_flagged(
    network: Network,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as s:
        f = s.execute(
            select(Finding).where(Finding.tenant_id == network.a.id, Finding.key == "M5:R01:P10")
        ).scalar_one()
        f.period_from, f.period_to = date(2026, 11, 1), date(2026, 11, 7)
        codes = {x.code for x in precheck.flags(s, f, TODAY)}
    assert {"holidays", "few_data"} <= codes


@pytest.mark.usefixtures("demo")
def test_the_draft_is_proposed_checked_and_counted_against_the_analysts_verdict(
    client: TestClient,
    network: Network,
    owner_engine: Engine,
    model: FakeModel,
) -> None:
    analyst = login(client, "analyst@a.ru")
    pending = _key(owner_engine, network, "M6:R04:P15:shortage")
    url = f"/api/findings/{pending}/precheck"
    # «reject» without a reason is corrected; then the draft is kept.
    model.replies += [draft("reject"), draft("reject", "data")]
    made = client.post(url, headers=analyst).json()
    assert made["draft"]["verdict"] == "reject" and made["draft"]["reason"] == "data"
    assert client.get(url, headers=analyst).json()["draft"]["id"] == made["draft"]["id"]
    # A number not in the facts: corrected once, then no draft.
    model.replies += [
        draft("confirm", rationale="Потери 99 999 ₽"),
        draft("confirm", rationale="Потери 99 999 ₽"),
    ]
    assert client.post(url, headers=analyst).status_code == 502
    stats = client.get("/api/ai/precheck/stats", headers=analyst).json()
    assert stats == {"drafts": 1, "decided": 0, "agreed": 0}
    # The analyst confirms against the draft: counted as a disagreement.
    client.post(f"/api/findings/{pending}/review", headers=analyst, json={"verdict": "confirm"})
    assert client.get("/api/ai/precheck/stats", headers=analyst).json() == {
        "drafts": 1,
        "decided": 1,
        "agreed": 0,
    }


@pytest.mark.usefixtures("demo")
def test_the_pre_check_is_for_reviewers_only(
    client: TestClient,
    network: Network,
    owner_engine: Engine,
    model: FakeModel,
) -> None:
    """TC-ISO: a director, another network — no flags, no draft, no stats."""
    pending = _key(owner_engine, network, "M6:R04:P15:shortage")
    for email in ("r01@a.ru", "admin@b.ru"):
        h = login(client, email)
        assert client.get(f"/api/findings/{pending}/precheck", headers=h).status_code in (403, 404)
        assert client.post(f"/api/findings/{pending}/precheck", headers=h).status_code in (403, 404)
    assert client.get("/api/ai/precheck/stats", headers=login(client, "r01@a.ru")).status_code == 403
    assert client.get("/api/ai/precheck/stats", headers=login(client, "admin@b.ru")).json() == {
        "drafts": 0,
        "decided": 0,
        "agreed": 0,
    }
    assert model.requests == []
