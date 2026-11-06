"""The data quality score as a director may see it (docs/12, «Оценка качества данных»; ADR 0009; code
review of stage 6.5, p. 4): only the parts of the findings shown to them, the score recomputed without the
rest; HQ sees it whole; another restaurant or another network — nothing (TC-ENG-35, TC-ENG-43)."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.insights.models import Finding
from app.overview.models import KpiSnapshot
from tests.conftest import Network, hq_task, login

TODAY = date(2026, 10, 20)
NEGATIVE = ["M7:A1:P01:negative", "M7:A1:P02:negative", "M7:A1:P03:negative"]


def _seed(owner_engine: Engine, network: Network) -> dict[str, UUID]:
    """A1 lost 25 (a missing export), 30 (three products below zero) and 10 (a dish without a recipe,
    a network finding): 100 − 65 = 35. Every finding is checked; no task yet."""
    a, a1 = network.a.id, network.a.restaurants["A1"]
    parts: list[dict[str, Any]] = [
        {"kind": "gap", "label": "Выгрузка не загружена", "points": 25, "findings": ["M7:A1:receipts"]},
        {"kind": "negative", "label": "Остаток по документам в минусе", "points": 30, "findings": NEGATIVE},
        {
            "kind": "no_recipe",
            "label": "Продается блюдо без техкарты",
            "points": 10,
            "findings": ["M7:net:M12"],
        },
    ]
    ids: dict[str, UUID] = {}
    with Session(owner_engine) as s, s.begin():
        for restaurant, score, dq_parts in ((a1, 35, parts), (None, 68, None)):
            s.add(
                KpiSnapshot(
                    tenant_id=a,
                    restaurant_id=restaurant,
                    computed_on=TODAY,
                    revenue=0,
                    data_quality=score,
                    data_quality_parts=dq_parts,
                )
            )
        for key in ["M7:A1:receipts", *NEGATIVE, "M7:net:M12"]:
            f = Finding(
                tenant_id=a,
                restaurant_id=None if ":net:" in key else a1,
                kind="problem",
                process="accounting",
                module="M7",
                key=key,
                title=key,
                actions=[],
                found_on=TODAY,
                review_status="confirmed",
            )
            s.add(f)
            s.flush()
            ids[key] = f.id
    return ids


def _kpi(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    kpi: dict[str, Any] = client.get("/api/overview/restaurants/A1", headers=headers).json()["kpi"]
    return kpi


def test_a_director_sees_the_parts_of_the_findings_shown_to_them_and_hq_the_whole_score(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    ids = _seed(owner_engine, network)
    director, hq = login(client, "director1@a.ru"), login(client, "admin@a.ru")
    # Nothing given to the director yet: no word of the data findings, the score without them
    assert (_kpi(client, director)["data_quality"], _kpi(client, director)["data_quality_parts"]) == (100, [])
    hq_task(owner_engine, ids["M7:A1:receipts"])
    # the missing export is shown to them now: 100 − 25 = 75, and only that reason
    mine = _kpi(client, director)
    assert mine["data_quality"] == 75
    assert mine["data_quality_parts"] == [{"label": "Выгрузка не загружена", "points": 25}]
    # HQ sees the whole score, the reasons by their points, the largest first
    whole = _kpi(client, hq)
    assert whole["data_quality"] == 35
    assert [p["points"] for p in whole["data_quality_parts"]] == [30, 25, 10]
    # Another restaurant's director and another network: not found, like a missing restaurant
    assert (
        client.get("/api/overview/restaurants/A1", headers=login(client, "director2@a.ru")).status_code == 404
    )
    assert client.get("/api/overview/restaurants/A1", headers=login(client, "admin@b.ru")).status_code == 404


def test_a_part_counts_only_the_findings_shown_to_the_director(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    ids = _seed(owner_engine, network)
    hq_task(owner_engine, ids["M7:A1:receipts"])
    hq_task(owner_engine, ids[NEGATIVE[0]])
    mine = _kpi(client, login(client, "director1@a.ru"))
    # one product below zero is shown: 10 points of it, not the 30 of all three → 100 − 25 − 10 = 65
    assert mine["data_quality_parts"] == [
        {"label": "Выгрузка не загружена", "points": 25},
        {"label": "Остаток по документам в минусе", "points": 10},
    ]
    assert mine["data_quality"] == 65
