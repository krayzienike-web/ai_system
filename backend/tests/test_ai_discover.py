"""Ideas of new findings (ADR 0008, stage 5.5): aggregates by the code, ideas by the model that point at the
rows they rest on, every number checked against those rows, a decision on each idea by the HQ."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai import discover
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.main import app
from app.tenancy.context import tool_session
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _table(r: ModelRequest) -> dict[str, Any]:
    facts: dict[str, Any] = json.loads(r.messages[0]["content"][0]["text"].split("\n", 1)[1])
    return facts


def _bread(table: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in table["write_offs_by_weekday"] if row["restaurant"] == "R07")


def idea(rows: list[str], text: str) -> dict[str, Any]:
    return {
        "title": "Списания по дням недели",
        "pattern": text,
        "rows": rows,
        "why_it_matters": "Лишние заказы",
        "rule_sketch": "Сравнить доли дней",
    }


@pytest.mark.usefixtures("demo")
def test_the_planted_weekday_pattern_is_in_the_aggregates(network: Network) -> None:
    """R07 orders the same bread every day and writes it off on Mondays and Tuesdays (docs/11)."""
    with tool_session(network.a.users["admin@a.ru"], network.a.id) as (session, _):
        table = discover.aggregates(session, TODAY)
    r07 = [row for row in table["write_offs_by_weekday"] if row["restaurant"] == "R07"]
    assert r07 and r07[0]["weekday"] in ("понедельник", "вторник"), table["write_offs_by_weekday"]
    ids = [row["id"] for items in table.values() for row in items]
    assert len(ids) == len(set(ids)) and all(
        row["table"] in table for items in table.values() for row in items
    )


@pytest.mark.usefixtures("demo")
def test_ideas_point_at_rows_every_number_is_checked_and_each_is_decided(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    analyst = login(client, "analyst@a.ru")

    def good(r: ModelRequest) -> Reply:
        row = _bread(_table(r))
        ideas = [
            idea(
                [row["id"]],
                f"В {row['restaurant']} {row['share_of_week']} списаний недели — {row['weekday']}",
            )
        ]
        return text_reply(json.dumps({"ideas": ideas}, ensure_ascii=False))

    def bad_row(_: ModelRequest) -> Reply:
        return text_reply(json.dumps({"ideas": [idea(["a999"], "Нет такой строки")]}, ensure_ascii=False))

    def foreign_number(r: ModelRequest) -> Reply:
        row = _bread(_table(r))
        return text_reply(
            json.dumps({"ideas": [idea([row["id"]], "Списания 77,7% недели")]}, ensure_ascii=False)
        )

    model.replies += [bad_row, good]
    made = client.post("/api/ai/finding-ideas", headers=analyst).json()
    assert len(made) == 1 and made[0]["evidence"][0]["restaurant"] == "R07"
    assert "a999" in model.requests[1].messages[-1]["content"][0]["text"]  # asked to correct
    model.replies += [foreign_number, foreign_number]
    assert client.post("/api/ai/finding-ideas", headers=analyst).status_code == 502
    listed = client.get("/api/ai/finding-ideas", headers=analyst).json()
    assert [i["id"] for i in listed] == [made[0]["id"]]
    decided = client.post(
        f"/api/ai/suggestions/{made[0]['id']}/decision", headers=analyst, json={"accepted": True}
    )
    assert decided.json()["status"] == "accepted"


@pytest.mark.usefixtures("demo")
def test_ideas_are_for_the_hq_only(client: TestClient, network: Network, model: FakeModel) -> None:
    """TC-ISO: a director sees no ideas, cannot ask for them nor decide; another network sees none."""
    model.replies.append(
        lambda r: text_reply(json.dumps({"ideas": [idea([_bread(_table(r))["id"]], "Хлеб")]}))
    )
    made = client.post("/api/ai/finding-ideas", headers=login(client, "analyst@a.ru")).json()
    director, foreign = login(client, "r01@a.ru"), login(client, "admin@b.ru")
    assert client.get("/api/ai/finding-ideas", headers=director).status_code == 403
    assert client.post("/api/ai/finding-ideas", headers=director).status_code == 403
    assert (
        client.post(
            f"/api/ai/suggestions/{made[0]['id']}/decision", headers=director, json={"accepted": True}
        ).status_code
        == 404
    )
    assert client.get("/api/ai/finding-ideas", headers=foreign).json() == []


def test_every_batch_of_ideas_is_kept_and_shown(network: Network, owner_engine: Engine) -> None:
    """Q21 (03.11.2026): «пока храним и показываем всё» — no cut at the latest ten."""
    from app.ai.models import AiSuggestion
    from app.core.db import get_sessionmaker
    from app.tenancy.context import load_access_context

    with Session(owner_engine) as s, s.begin():
        for n in range(12):
            s.add(
                AiSuggestion(
                    tenant_id=network.a.id,
                    kind="finding_idea",
                    content={"n": n},
                    basis={},
                    prompt="discover",
                    prompt_version=1,
                )
            )
    with get_sessionmaker()() as s:
        ctx = load_access_context(s, network.a.users["analyst@a.ru"], network.a.id)
    assert ctx is not None
    assert len(discover.ideas(ctx)) == 12
