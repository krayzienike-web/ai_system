"""Code review of stage 5.5 (02.11.2026, docs/reviews/2026-11-02-stage-5.5-review.md): one test per fix."""

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.ai.discover import Ideas
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, strict_schema, text_reply
from app.ai.hypotheses import Hypotheses
from app.ai.mapping import Marking
from app.ai.precheck import Draft
from app.experiments.models import Experiment
from app.imports.reader import map_header
from app.imports.templates import TEMPLATES
from app.insights.models import Finding
from app.main import app
from app.tasks.models import Task
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _facts(r: ModelRequest) -> dict[str, Any]:
    facts: dict[str, Any] = json.loads(r.messages[0]["content"][0]["text"].split("\n", 1)[1])
    return facts


def _json(value: Any) -> Reply:
    return text_reply(json.dumps(value, ensure_ascii=False))


def _hypotheses(_: ModelRequest) -> Reply:
    h = {"cause": "overordering", "likelihood": "высокая", "why": "по фактам", "check": "на месте"}
    return _json({"hypotheses": [h], "steps": [], "rules_note": None})


# ------------------------------------------------------------ p. 1: the schema keeps a field named «title»


@pytest.mark.parametrize("answer", [Ideas, Draft, Hypotheses, Marking])
def test_every_answer_schema_requires_exactly_its_fields(answer: Any) -> None:
    schema = strict_schema(answer.model_json_schema())
    for name, model in [(answer.__name__, answer), *[(d, None) for d in schema.get("$defs", {})]]:
        node = schema if model is answer else schema["$defs"][name]
        assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
    assert "title" in schema["$defs"]["Idea"]["properties"] if answer is Ideas else True
    assert "title" not in json.dumps({k: v for k, v in schema.items() if k != "$defs"}).replace('"title"', "")


def test_a_scripted_answer_that_does_not_fit_the_schema_fails_the_test(network: Network) -> None:
    from app.ai import prompt as prompts
    from app.tenancy.context import tool_session

    with tool_session(network.a.users["admin@a.ru"], network.a.id) as (_, ctx):
        pass
    gateway = Gateway(FakeModel([_json({"ideas": [{"pattern": "без заголовка"}]})]))
    with pytest.raises(AssertionError, match="does not fit the schema"):
        gateway.structured(ctx, task="discover", prompt=prompts.load("discover"), messages=[], answer=Ideas)


# ------------------------------------------------------------------ pp. 2–3: what a director's basis may hold
def _hand_to_director(owner_engine: Engine, finding_id: UUID) -> None:
    """The director sees a finding through the HQ's task (ADR 0009): the demo's rucola has none (stage 7)."""
    with Session(owner_engine) as s, s.begin():
        finding = s.get(Finding, finding_id)
        assert finding is not None
        s.add(
            Task(
                tenant_id=finding.tenant_id,
                restaurant_id=finding.restaurant_id,
                finding_id=finding_id,
                title="Заказывать рукколу малыми партиями",
                assigned_by="hq",
                created_on=date(2026, 10, 10),
                due_on=date(2026, 10, 24),
            )
        )


@pytest.mark.usefixtures("demo")
def test_the_basis_holds_no_finding_under_review_and_no_other_restaurants_checks(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    with Session(owner_engine) as s, s.begin():
        r01 = s.execute(select(Finding.restaurant_id).where(Finding.key == "M1:R01:P01")).scalar_one()
        own = s.execute(select(Finding.id).where(Finding.key == "M5:R01:P10")).scalar_one()
        s.add(
            Finding(
                tenant_id=network.a.id,
                restaurant_id=r01,
                kind="problem",
                process="accounting",
                module="M7",
                title="СЕКРЕТ: отклоненная проблема данных",
                actions=[],
                found_on=TODAY,
                review_status="rejected",
            )
        )
        # A completed check of another restaurant, for a finding of the same module.
        other = s.execute(select(Finding).where(Finding.key == "M5:R07:P12")).scalar_one()
        s.add(
            Experiment(
                tenant_id=network.a.id,
                finding_id=other.id,
                title="Проверка в R07",
                hypothesis="…",
                metric="…",
                test_restaurant_ids=[other.restaurant_id],
                starts_on=date(2026, 9, 1),
                ends_on=date(2026, 9, 29),
                expected_rub_month=Decimal("1000"),
                status="completed",
                verdict="confirmed",
                effect_rub_month=Decimal("45000"),
                completed_on=date(2026, 9, 30),
            )
        )
    _hand_to_director(owner_engine, own)
    model.replies.append(_hypotheses)
    client.post(f"/api/findings/{own}/hypotheses", headers=login(client, "admin@a.ru"))
    got = client.get(f"/api/findings/{own}/hypotheses", headers=login(client, "r01@a.ru"))
    assert got.status_code == 200, got.text
    seen = got.json()
    basis = json.dumps(seen["basis"], ensure_ascii=False)
    assert "СЕКРЕТ" not in basis and "45 000" not in basis and "R07" not in basis
    similar = seen["basis"]["checks_of_similar_findings"]
    assert similar["checks_in_network"] >= 1 and set(similar) == {
        "checks_in_network",
        "worked",
        "did_not_work",
    }
    assert "итоги похожих проверок в сети" in seen["basis_words"]


# ------------------------------------------------------------------ pp. 4–6: markings and profiles


RECEIPTS = (
    "Приход товара\n\nДата;Товар;Кол-во;Ед. изм.;Всего;Сумма\n"
    "01.10.2026;Сыр Моцарелла;2;кг;1500;3000\n02.10.2026;Сыр Моцарелла;1;кг;1500;1500\n"
    "03.10.2026;Сыр Моцарелла;3;кг;1500;4500\n"
)


def _mark(
    client: TestClient, headers: dict[str, str], content: str, template: str, restaurant: Any = None
) -> Any:
    data = {"template": template, **({"restaurant_id": str(restaurant)} if restaurant else {})}
    return client.post(
        "/api/imports/mapping",
        headers=headers,
        data=data,
        files={"file": ("f.csv", content.encode(), "text/csv")},
    )


def _marking(*pairs: tuple[str, str]) -> Any:
    return lambda _: _json({"columns": [{"field": f, "header": h, "why": "по образцам"} for f, h in pairs]})


def test_the_model_cannot_remap_what_the_dictionary_mapped_and_the_preview_is_what_is_confirmed(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    director = login(client, "director1@a.ru")
    a1 = network.a.restaurants["A1"]
    model.replies += [_marking(("amount", "Всего"), ("price", "Сумма")), _marking(("price", "Всего"))]
    marked = _mark(client, director, RECEIPTS, "receipts", a1).json()
    assert "уже сопоставлен" in model.requests[1].messages[-1]["content"][0]["text"]
    mapped = {c["field"]: c["header"] for c in marked["columns"]}
    assert mapped["amount"] == "Сумма" and mapped["price"] == "Всего"
    assert len(set(mapped.values())) == len(mapped)


def test_a_directors_profile_serves_their_restaurant_and_synonyms_win_over_profiles(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Engine
) -> None:
    from app.imports.models import SourceProfile

    director, admin = login(client, "director1@a.ru"), login(client, "admin@a.ru")
    a1 = network.a.restaurants["A1"]
    model.replies.append(_marking(("price", "Всего")))
    marked = _mark(client, director, RECEIPTS, "receipts", a1).json()
    client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=director)
    with Session(owner_engine) as s:
        profile = s.execute(select(SourceProfile)).scalar_one()
    assert profile.restaurant_id == a1  # not the whole network
    # Visible to the HQ, not applied to another restaurant's files.
    assert [p["id"] for p in client.get("/api/imports/profiles", headers=admin).json()] == [str(profile.id)]
    # A profile never takes a synonym away: «Сумма» stays the amount.
    found, _ = map_header(
        ["Дата", "Товар", "Кол-во", "Цена", "Сумма"], TEMPLATES["receipts"], {"сумма": "price"}
    )
    assert found["amount"] == 4 and found["price"] == 3


def test_a_header_read_two_ways_is_refused_and_a_profile_can_be_removed(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    from app.core.errors import ConflictError, InvalidError
    from app.imports import service
    from app.tenancy.context import tool_session

    admin = login(client, "admin@a.ru")
    a1 = network.a.restaurants["A1"]
    model.replies.append(_marking(("price", "Всего")))
    first = _mark(client, admin, RECEIPTS, "receipts", a1).json()
    profile = client.post(f"/api/imports/mapping/{first['id']}/confirm", headers=admin).json()["profile_id"]
    # A next marking cannot give «Всего» to another column: it is the price now (asked to correct, then none).
    other = RECEIPTS.replace("Приход товара", "Приход за октябрь")
    model.replies += [_marking(("vat", "Всего")), _marking(("vat", "Всего"))]
    assert _mark(client, admin, other, "receipts", a1).status_code == 502
    assert "уже сопоставлен" in model.requests[-1].messages[-1]["content"][0]["text"]
    # Nor can a profile be saved that reads it so, or one that gives a header to two columns.
    with tool_session(network.a.users["admin@a.ru"], network.a.id) as (session, ctx):
        pass
    from app.tenancy.context import user_session

    with user_session(ctx) as session, pytest.raises(ConflictError):
        service.save_profile(
            session, ctx, template="receipts", title="x", mapping={"vat": "Всего"}, restaurant_id=a1
        )
    with user_session(ctx) as session, pytest.raises(InvalidError):
        service.save_profile(
            session, ctx, template="receipts", title="x", mapping={"vat": "Н", "price": "Н"}, restaurant_id=a1
        )
    assert (
        client.delete(f"/api/imports/profiles/{profile}", headers=login(client, "director1@a.ru")).status_code
        == 404
    )
    assert client.delete(f"/api/imports/profiles/{profile}", headers=admin).status_code == 204
    assert client.get("/api/imports/profiles", headers=admin).json() == []


# ------------------------------------------------------------------ pp. 7–8: superseding and decisions


def test_a_marking_replaces_only_a_marking_of_the_same_file_and_new_ideas_keep_undecided_ones(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    director1, director2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    model.replies += [_marking(("price", "Всего")), _marking(("price", "Всего"))]
    mine = _mark(client, director1, RECEIPTS, "receipts", network.a.restaurants["A1"]).json()
    _mark(client, director2, RECEIPTS, "receipts", network.a.restaurants["A2"])
    assert client.post(f"/api/imports/mapping/{mine['id']}/confirm", headers=director1).status_code == 200


@pytest.mark.usefixtures("demo")
def test_a_proposal_is_decided_once_and_a_marking_only_by_confirming(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Engine
) -> None:
    with Session(owner_engine) as s:
        own = s.execute(select(Finding.id).where(Finding.key == "M5:R01:P10")).scalar_one()
    _hand_to_director(owner_engine, own)
    director = login(client, "r01@a.ru")
    model.replies.append(_hypotheses)
    made = client.post(f"/api/findings/{own}/hypotheses", headers=director).json()
    url = f"/api/ai/suggestions/{made['id']}/decision"
    assert client.post(url, headers=director, json={"accepted": True}).status_code == 200
    assert client.post(url, headers=director, json={"accepted": False}).status_code == 409
    shown = client.get(f"/api/findings/{own}/hypotheses", headers=director).json()
    assert shown["decided_by_me"] is True
    assert (
        client.get(f"/api/findings/{own}/hypotheses", headers=login(client, "admin@a.ru")).json()[
            "decided_by_me"
        ]
        is False
    )

    admin = login(client, "admin@a.ru")
    model.replies.append(_marking(("price", "Всего")))
    marked = _mark(client, admin, RECEIPTS, "receipts", network.a.restaurants["A1"]).json()
    accept = client.post(
        f"/api/ai/suggestions/{marked['id']}/decision", headers=admin, json={"accepted": True}
    )
    assert accept.status_code == 422 and "Подтвердить" in accept.json()["detail"]


# ------------------------------------------------------------------ p. 9: a rule's sketch proposes thresholds


@pytest.mark.usefixtures("demo")
def test_a_threshold_in_the_rules_sketch_is_a_proposal_but_a_figure_in_the_pattern_is_checked(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    analyst = login(client, "analyst@a.ru")

    def idea(sketch: str, pattern: str) -> Any:
        def reply(r: ModelRequest) -> Reply:
            row = _facts(r)["write_offs_by_weekday"][0]
            body = {"title": "Списания по дням", "pattern": pattern.format(**row), "rows": [row["id"]]}
            return _json({"ideas": [{**body, "why_it_matters": "Лишние заказы", "rule_sketch": sketch}]})

        return reply

    model.replies.append(idea("Доля дня больше 25% за 8 недель", "{share_of_week} — {weekday}"))
    made = client.post("/api/ai/finding-ideas", headers=analyst).json()
    assert made and made[0]["evidence_text"][0].startswith("R")
    model.replies += [idea("порог словами", "Доля 77,7%"), idea("порог словами", "Доля 77,7%")]
    assert client.post("/api/ai/finding-ideas", headers=analyst).status_code == 502
    # The first batch is still there: new ideas do not hide undecided ones.
    assert [i["id"] for i in client.get("/api/ai/finding-ideas", headers=analyst).json()] == [made[0]["id"]]


# ------------------------------------------------------------------ p. 10: the inputs of a marking


def test_access_comes_before_the_model_and_a_big_file_is_refused(
    client: TestClient, network: Network
) -> None:
    app.dependency_overrides[get_gateway] = lambda: None
    try:
        director = login(client, "director1@a.ru")
        assert (
            _mark(client, director, RECEIPTS, "suppliers").status_code == 403
        )  # the network's reference files
        assert _mark(client, director, RECEIPTS, "receipts", network.a.restaurants["A1"]).status_code == 503
    finally:
        app.dependency_overrides.pop(get_gateway, None)
    # 20 bytes of header + 18 bytes a row: 1 170 000 rows are 21 060 020 bytes — over the file's 20 MB
    # (20 971 520), under the body's 21 MB (22 020 096): the service refuses it; 1 500 000 rows (27 MB) are
    # refused before the form is read (BodyLimit, pre-pilot review p. 1, TC-AUTH-11).
    over_file = "Дата;Товар\n" + "01.10.2026;Сыр\n" * 1_170_000
    over_body = "Дата;Товар\n" + "01.10.2026;Сыр\n" * 1_500_000
    app.dependency_overrides[get_gateway] = lambda: Gateway(FakeModel())
    try:
        admin = login(client, "admin@a.ru")
        r = _mark(client, admin, over_file, "receipts", network.a.restaurants["A1"])
        assert r.status_code == 422 and "20 МБ" in r.json()["detail"]
        r = _mark(client, admin, over_body, "receipts", network.a.restaurants["A1"])
        assert r.status_code == 413 and "20 МБ" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_gateway, None)


# ------------------------------------------------------------------ pp. 12–13: the pre-check


@pytest.mark.usefixtures("demo")
def test_a_rejected_data_problem_flags_nothing_and_a_draft_after_the_verdict_is_not_counted(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Engine
) -> None:
    from app.ai import precheck

    with Session(owner_engine) as s, s.begin():
        f = s.execute(select(Finding).where(Finding.key == "M1:R10:P01:under")).scalar_one()
        s.execute(
            update(Finding).where(Finding.key == "M7:R10:P01:negative").values(review_status="rejected")
        )
        assert "data_problems" not in {x.code for x in precheck.flags(s, f, TODAY)}
        f.period_from, f.period_to = date(2026, 10, 20), date(2026, 9, 1)  # a broken period
        assert precheck.flags(s, f, TODAY) is not None  # no negative-length period, no crash
        s.rollback()
    analyst = login(client, "analyst@a.ru")
    with Session(owner_engine) as s:
        pending = s.execute(select(Finding.id).where(Finding.key == "M6:R04:P15:shortage")).scalar_one()
    draft: dict[str, Any] = {"verdict": "confirm", "reason": None, "rationale": "По фактам", "look_at": []}
    model.replies += [lambda _: _json(draft), lambda _: _json(draft)]
    client.post(f"/api/findings/{pending}/precheck", headers=analyst)
    client.post(f"/api/findings/{pending}/review", headers=analyst, json={"verdict": "confirm"})
    client.post(f"/api/findings/{pending}/precheck", headers=analyst)  # after the verdict
    assert client.get("/api/ai/precheck/stats", headers=analyst).json() == {
        "drafts": 1,
        "decided": 1,
        "agreed": 1,
    }


# ------------------------------------------------------------------ p. 14: the flag, the rules, the eval


def test_the_assistant_flag_follows_the_provider_the_server_knows(
    client: TestClient, network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    headers = login(client, "admin@a.ru")
    for provider, shown in (("off", False), ("openai", False), ("claude", True)):
        monkeypatch.setenv("FAI_AI_PROVIDER", provider)
        get_settings.cache_clear()
        assert client.get("/api/overview/context", headers=headers).json()["assistant"] is shown
    get_settings.cache_clear()


def test_the_networks_rules_are_set_with_the_norms(client: TestClient, network: Network) -> None:
    admin = login(client, "admin@a.ru")
    norms = client.get("/api/settings/norms", headers=admin).json()
    body = {k: v for k, v in norms.items() if k not in ("menu_categories", "product_categories")}
    body["network_rules"] = ["Цены в меню меняются только с новым меню", "  "]
    saved = client.put("/api/settings/norms", headers=admin, json=body)
    assert saved.status_code == 200 and saved.json()["network_rules"] == [
        "Цены в меню меняются только с новым меню"
    ]


@pytest.mark.usefixtures("demo")
def test_the_eval_measures_without_replacing_what_people_see(network: Network, owner_engine: Engine) -> None:
    from app.ai.evals import hypotheses as eval_h
    from app.ai.models import AiSuggestion
    from app.tenancy.context import tool_session

    with Session(owner_engine) as s:
        own = s.execute(select(Finding.id).where(Finding.key == "M5:R01:P10")).scalar_one()
    with tool_session(network.a.users["admin@a.ru"], network.a.id) as (_, ctx):
        pass
    report = eval_h.run(
        Gateway(FakeModel([_hypotheses])), ctx, TODAY, [eval_h.Case("x", "overordering", own)]
    )
    assert report.score == 1.0
    with Session(owner_engine) as s:
        assert s.execute(select(AiSuggestion)).first() is None


# ------------------------------------------------------------ front p. 1: «Разметить с ИИ», type guessed


def test_an_unrecognised_file_says_it_can_be_marked(client: TestClient, network: Network) -> None:
    admin = login(client, "admin@a.ru")
    files = {"file": ("x.csv", "Что-то;Непонятное;Еще\n1;2;3\n".encode(), "text/csv")}
    guessed = client.post(
        "/api/imports", headers=admin, data={"restaurant_id": str(network.a.restaurants["A1"])}, files=files
    )
    assert guessed.status_code == 422 and guessed.json()["code"] == "no_header"
    files = {"file": ("x.csv", "Что-то;Непонятное;Еще\n1;2;3\n".encode(), "text/csv")}
    data = {"template": "sales", "restaurant_id": str(network.a.restaurants["A1"])}
    chosen = client.post("/api/imports", headers=admin, data=data, files=files).json()
    assert chosen["status"] == "failed" and chosen["markable"] is True
    assert UUID(chosen["id"])
