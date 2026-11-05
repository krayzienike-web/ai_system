"""«Почему так» по находке (ADR 0008, stage 5.5) on the demo network, with the scripted model: the code
gathers the facts, the model proposes causes from a fixed list, every number is checked, the card's rules
decide who sees what, a person decides."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.ai.claude import ClaudeModel
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, strict_schema, text_reply
from app.ai.hypotheses import CAUSES, Hypotheses
from app.ai.models import AiSuggestion
from app.insights.models import Finding
from app.main import app
from app.norms.models import NormSettings
from app.tenancy.models import Restaurant
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)

RULE = "Цены в меню меняются только вместе с новым меню, раз в полгода"


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


@pytest.fixture
def world(network: Network, owner_engine: Engine, demo: dict[str, UUID]) -> dict[str, Any]:  # noqa: F811
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        norms = s.execute(select(NormSettings).where(NormSettings.tenant_id == network.a.id)).scalar()
        if norms is None:  # the network keeps the default norms: give it a row with its rule
            norms = NormSettings(tenant_id=network.a.id, food_cost_target_pct=30, loss_default_pct=2)
            s.add(norms)
        norms.network_rules = [RULE]
        places = {
            r.code: r
            for r in s.execute(select(Restaurant).where(Restaurant.tenant_id == network.a.id)).scalars()
        }
        shown = Finding.review_status.is_(None) | (Finding.review_status == "confirmed")

        def key(k: str) -> UUID:
            return s.execute(
                select(Finding.id).where(Finding.tenant_id == network.a.id, Finding.key == k)
            ).scalar_one()

        pending = s.execute(
            select(Finding.id).where(
                Finding.restaurant_id == places["R01"].id, Finding.review_status == "pending"
            )
        ).scalar()
        if pending is None:  # make one: an R01 finding waiting for review
            pending = key("M1:R01:P01")
            s.execute(update(Finding).where(Finding.id == pending).values(review_status="pending"))
        greens = (
            s.execute(
                select(Finding.id).where(Finding.key == "M5:R01:P05", Finding.tenant_id == network.a.id)
            ).scalar()
            or s.execute(
                select(Finding.id).where(
                    Finding.restaurant_id == places["R01"].id, Finding.module == "M5", shown
                )
            ).scalar_one()
        )
        other = s.execute(select(Finding.id).where(Finding.restaurant_id == places["R02"].id, shown)).scalar()
        net = s.execute(select(Finding.id).where(Finding.key == "M2:net:M07")).scalar()
    return {"places": places, "own": greens, "pending": pending, "other": other, "net": net}


def _facts(r: ModelRequest) -> dict[str, Any]:
    text = r.messages[0]["content"][0]["text"]
    facts: dict[str, Any] = json.loads(text.split("\n", 1)[1])
    return facts


def answer(causes: list[str], *, extra: str = "") -> Any:
    """A proposal that quotes only what the facts hold."""

    def reply(r: ModelRequest) -> Reply:
        f = _facts(r)
        effect = f["finding"].get("effect_per_month", "")
        return text_reply(
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "cause": c,
                            "likelihood": "высокая",
                            "why": f"По фактам: {effect}{extra}",
                            "check": "Взвесить",
                        }
                        for c in causes
                    ],
                    "steps": ["Обучить смену"],
                    "rules_note": None,
                },
                ensure_ascii=False,
            )
        )

    return reply


def test_the_schema_sent_to_the_model_is_closed_and_complete() -> None:
    schema = strict_schema(Hypotheses.model_json_schema())
    assert schema["additionalProperties"] is False and set(schema["required"]) == {
        "hypotheses",
        "steps",
        "rules_note",
    }
    item = schema["$defs"]["Hypothesis"]
    assert item["additionalProperties"] is False and set(item["required"]) == {
        "cause",
        "likelihood",
        "why",
        "check",
    }
    assert set(item["properties"]["cause"]["enum"]) == set(CAUSES)
    no_client: Any = object()
    params = ClaudeModel(client=no_client).params(
        ModelRequest("claude-opus-5-5", "s", [], output_schema=schema)
    )
    assert params["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": schema},
    }


def test_hypotheses_are_proposed_from_the_facts_and_kept(
    client: TestClient, world: dict[str, Any], model: FakeModel
) -> None:
    director = login(client, "r01@a.ru")
    url = f"/api/findings/{world['own']}/hypotheses"
    assert client.get(url, headers=director).json() is None
    model.replies.append(answer(["overordering", "storage"]))
    made = client.post(url, headers=director).json()
    assert [h["cause"] for h in made["hypotheses"]] == ["overordering", "storage"]
    assert made["hypotheses"][0]["cause_title"] == CAUSES["overordering"]
    assert made["status"] == "proposed" and made["basis"]["network_rules"] == [RULE]
    facts = _facts(model.requests[0])
    assert facts["finding"]["restaurant"] == world["places"]["R01"].name
    assert (
        "write_off_reasons" in facts and "inventory_count_days" in facts and "causes_to_choose_from" in facts
    )
    assert client.get(url, headers=director).json()["id"] == made["id"]
    # A new proposal replaces the old one; the old one stays in the log as superseded.
    model.replies.append(answer(["weekday_demand"]))
    again = client.post(url, headers=director).json()
    assert client.get(url, headers=director).json()["id"] == again["id"] != made["id"]


def test_a_number_not_in_the_facts_is_corrected_once_then_there_is_no_proposal(
    client: TestClient, world: dict[str, Any], model: FakeModel, owner_engine: Engine
) -> None:
    headers = login(client, "admin@a.ru")
    url = f"/api/findings/{world['own']}/hypotheses"
    model.replies += [answer(["overordering"], extra=", это 87 654 ₽ за год"), answer(["overordering"])]
    assert client.post(url, headers=headers).status_code == 200
    assert "87654" in model.requests[1].messages[-1]["content"][0]["text"]
    model.replies += [
        answer(["overordering"], extra=", 87 654 ₽"),
        answer(["overordering"], extra=", 87 654 ₽"),
    ]
    r = client.post(url, headers=headers)
    assert r.status_code == 502
    # Too many hypotheses or a repeated cause is corrected the same way; nonsense JSON is no proposal.
    model.replies += [answer(["yield", "yield"]), answer(["yield"])]
    assert client.post(url, headers=headers).status_code == 200
    model.replies.append(text_reply("не json"))
    assert client.post(url, headers=headers).status_code == 502
    with Session(owner_engine) as s:
        kept = (
            s.execute(select(AiSuggestion.status).where(AiSuggestion.subject_id == world["own"]))
            .scalars()
            .all()
        )
    assert sorted(kept) == ["proposed", "superseded"]  # failed attempts keep nothing


def test_the_cards_rules_decide_who_sees_the_hypotheses(
    client: TestClient, world: dict[str, Any], model: FakeModel
) -> None:
    """TC-ISO: a director — only for their own findings that passed review; another network — nothing; the
    facts of an R01 finding, gathered for the HQ, hold no other restaurant's name."""
    admin, director, foreign = (
        login(client, "admin@a.ru"),
        login(client, "r01@a.ru"),
        login(client, "admin@b.ru"),
    )
    model.replies += [answer(["portioning"]), answer(["portioning"])]
    made = client.post(f"/api/findings/{world['own']}/hypotheses", headers=admin).json()
    basis = json.dumps(made["basis"], ensure_ascii=False)
    assert not [r.name for code, r in world["places"].items() if code != "R01" and r.name in basis]
    pending = client.post(f"/api/findings/{world['pending']}/hypotheses", headers=admin).json()
    for path in (world["pending"], world["other"], world["net"]):
        assert client.get(f"/api/findings/{path}/hypotheses", headers=director).status_code == 404
        assert client.post(f"/api/findings/{path}/hypotheses", headers=director).status_code == 404
    assert (
        client.post(
            f"/api/ai/suggestions/{pending['id']}/decision", headers=director, json={"accepted": True}
        ).status_code
        == 404
    )
    assert client.get(f"/api/findings/{world['own']}/hypotheses", headers=foreign).status_code == 404
    assert (
        client.post(
            f"/api/ai/suggestions/{made['id']}/decision", headers=foreign, json={"accepted": True}
        ).status_code
        == 404
    )


def test_a_person_decides_and_without_the_model_nothing_is_proposed(
    client: TestClient, world: dict[str, Any], model: FakeModel
) -> None:
    director = login(client, "r01@a.ru")
    model.replies.append(answer(["overordering"]))
    made = client.post(f"/api/findings/{world['own']}/hypotheses", headers=director).json()
    decided = client.post(
        f"/api/ai/suggestions/{made['id']}/decision",
        headers=director,
        json={"accepted": True, "note": "Проверим"},
    ).json()
    assert decided["status"] == "accepted"
    assert (
        client.get(f"/api/findings/{world['own']}/hypotheses", headers=director).json()["status"]
        == "accepted"
    )
    app.dependency_overrides[get_gateway] = lambda: None
    r = client.post(f"/api/findings/{world['own']}/hypotheses", headers=director)
    assert r.status_code == 503 and r.json()["detail"] == "Ассистент пока не подключен"


def test_the_eval_finds_every_planted_anomaly_and_grades_the_top_three(
    world: dict[str, Any], owner_engine: Engine, network: Network
) -> None:
    """TC-AI: the «почему так» eval on the demo network — every planted anomaly maps to the engine's finding,
    a model naming the planted cause scores 100 %, one that always says «theft» fails the 80 % mark."""
    import json as json_

    from app.ai.evals import hypotheses as eval_h
    from app.demo.generator import generate
    from app.tenancy.context import tool_session

    anomalies = json_.loads(generate(seed=42).files["anomalies.json"])["anomalies"]
    with Session(owner_engine) as s:
        cases = eval_h.cases(s, network.a.id, anomalies)
        titles = {c.finding_id: s.get(Finding, c.finding_id).title for c in cases if c.finding_id}  # type: ignore[union-attr]
    assert len(cases) == 20 and all(c.finding_id for c in cases), [
        c.anomaly for c in cases if not c.finding_id
    ]
    cause_of = {titles[c.finding_id]: c.cause for c in cases if c.finding_id}

    def oracle(r: ModelRequest) -> Reply:
        f = _facts(r)
        cause = cause_of[f["finding"]["title"]]
        h = {"cause": cause, "likelihood": "высокая", "why": "по фактам", "check": "на месте"}
        return text_reply(
            json.dumps({"hypotheses": [h], "steps": [], "rules_note": None}, ensure_ascii=False)
        )

    def theft(_: ModelRequest) -> Reply:
        h = {"cause": "theft", "likelihood": "низкая", "why": "по фактам", "check": "на месте"}
        return text_reply(
            json.dumps({"hypotheses": [h], "steps": [], "rules_note": None}, ensure_ascii=False)
        )

    with tool_session(network.a.users["admin@a.ru"], network.a.id) as (_, ctx):
        pass
    right = eval_h.run(Gateway(FakeModel([oracle] * 20), per_user_day=1000), ctx, TODAY, cases)
    assert right.score == 1.0 and right.passed, right.summary()
    wrong = eval_h.run(Gateway(FakeModel([theft] * 20), per_user_day=1000), ctx, TODAY, cases)
    # Stage 6.5 planted two till anomalies whose cause is theft: «always theft» guesses only those
    assert wrong.score == pytest.approx(2 / 20, abs=0.01) and not wrong.passed
    assert "ждали portioning" in wrong.summary()
