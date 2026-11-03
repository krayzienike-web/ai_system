"""Code review of stage 6 (03.11.2026, docs/reviews/2026-11-03-stage-6-review.md): every fix with its test
(TC-DG-23…)."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import worker
from app.ai import digest_writer
from app.ai.evals import digest as digest_eval
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, strict_schema, text_reply
from app.digests import builder, weekly
from app.digests.models import Digest, Disagreement
from app.main import app
from app.tasks.models import Task, TaskStatus
from app.tenancy.models import Restaurant
from tests.conftest import Network, login
from tests.test_digests import WEEK, _assemble, _ctx, _r
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


def _texts(headline: str, item: Any = "Проверьте накладные.") -> Callable[[ModelRequest], Reply]:
    """Every item gets `item` (a text, or a function of the item's facts)."""

    def reply(request: ModelRequest) -> Reply:
        facts = json.loads(request.messages[0]["content"][0]["text"].split("\n", 1)[1])
        items = facts["problems"] + facts["opportunities"] + facts["risks"]
        body = {
            "headline": headline.format(**facts["on_table"]),
            "items": [
                {"finding_id": i["finding_id"], "text": item(i, items) if callable(item) else item}
                for i in items
            ],
        }
        return text_reply(json.dumps(body, ensure_ascii=False))

    return reply


def _digest(owner_engine: Engine, digest_id: UUID) -> Digest:
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None
        s.expunge(d)
        return d


@pytest.mark.usefixtures("demo")
def test_p1_a_restaurants_digest_holds_no_network_revenue(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """The network's snapshot holds the sum of all revenue: never in a director's digest, prompt or screen."""
    admin = _ctx(network, "admin@a.ru", owner_engine)
    r01 = _r(owner_engine, network, "R01")
    seen: list[str] = []

    def spy(request: ModelRequest) -> Reply:
        seen.append(request.messages[0]["content"][0]["text"])
        return _texts("На столе {total} в месяц.")(request)

    d = _digest(
        owner_engine, _assemble(admin, r01, write=digest_writer.writer(Gateway(FakeModel([spy])), admin))
    )
    net = _digest(owner_engine, _assemble(admin, None))
    assert d.input["network_average"] and "revenue" not in d.input["network_average"]
    network_revenue = net.input["kpis"]["revenue"]
    assert network_revenue and network_revenue not in seen[0]
    shown = client.get("/api/digests/latest", headers=login(client, "r01@a.ru")).json()
    assert shown["network_average"]["revenue"] is None and network_revenue not in json.dumps(
        shown, ensure_ascii=False
    )


@pytest.mark.usefixtures("demo")
def test_p2_the_rebuild_holds_no_connection_while_the_model_thinks(client: TestClient) -> None:
    from sqlalchemy.pool import QueuePool

    from app.core.db import get_engine

    held: list[int] = []

    def probe(request: ModelRequest) -> Reply:
        pool = get_engine().pool
        assert isinstance(pool, QueuePool)
        held.append(pool.checkedout())
        return _texts("Главное.")(request)

    app.dependency_overrides[get_gateway] = lambda: Gateway(FakeModel([probe]))
    try:
        assert (
            client.post("/api/digests/rebuild", json={}, headers=login(client, "r01@a.ru")).status_code == 200
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)
    assert held == [0]


@pytest.mark.usefixtures("demo")
def test_p3_builds_at_once_never_fail_and_the_later_read_wins(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    with ThreadPoolExecutor(2) as pool:  # two first builds of one digest: no unique-index error
        ids = list(pool.map(lambda _: _assemble(admin, None), range(2)))
    assert ids[0] == ids[1]

    # A slow build (the model thinking) read its data before a quick one: it does not overwrite the newer one.
    def slow(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        _assemble(admin, None)  # the quick rebuild by rules, read later
        return {"headline": "Старый текст модели", "items": {}}, 2

    _assemble(admin, None, write=slow)
    with Session(owner_engine) as s:
        rows = s.execute(select(Digest).where(Digest.restaurant_id.is_(None))).scalars().all()
    assert len(rows) == 1 and rows[0].source == "rules"


@pytest.mark.usefixtures("demo")
def test_p4_invented_counts_send_the_text_to_the_rules(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    lie = _texts("На столе {total} в месяц. За неделю выполнено 7 задач, в зоне риска 4 процесса.")
    fake = FakeModel([lie, lie])
    d = _digest(owner_engine, _assemble(admin, None, write=digest_writer.writer(Gateway(fake), admin)))
    assert d.source == "rules" and len(fake.requests) == 2
    assert "Проверка: числа" in fake.requests[1].messages[-1]["content"][0]["text"]


@pytest.mark.usefixtures("demo")
def test_p5_an_items_text_quotes_only_its_own_figures(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)

    def neighbours(i: dict[str, Any], items: list[dict[str, Any]]) -> str:
        other = next(x for x in items if x["finding_id"] != i["finding_id"] and x["effect_per_month"])
        return f"Теряем {other['effect_per_month']} в месяц."

    swap = _texts("Главное.", neighbours)
    d = _digest(
        owner_engine,
        _assemble(admin, None, write=digest_writer.writer(Gateway(FakeModel([swap, swap])), admin)),
    )
    assert d.source == "rules"
    own = _texts("Главное.", lambda i, _: f"Теряем {i['effect_per_month'] or 'деньги'} в месяц.")
    d = _digest(
        owner_engine, _assemble(admin, None, write=digest_writer.writer(Gateway(FakeModel([own])), admin))
    )
    assert d.source == "model"


def test_p6_the_prompt_asks_for_the_figures_as_written() -> None:
    from app.ai import prompt

    p = prompt.load("digest")
    assert p.version == 2 and "38 412 ₽" in p.text and "«38 тыс ₽»\nнельзя" in p.text


@pytest.mark.usefixtures("demo")
def test_p7_a_rebuild_never_replaces_the_models_text_by_rules(client: TestClient) -> None:
    director = login(client, "r01@a.ru")
    fake = FakeModel([_texts("Главное от модели.")])
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    try:
        assert client.post("/api/digests/rebuild", json={}, headers=director).json()["source"] == "model"
        r = client.post("/api/digests/rebuild", json={}, headers=director)  # the model has nothing to say now
    finally:
        app.dependency_overrides.pop(get_gateway, None)
    assert r.status_code == 409 and "осталась прежней" in r.json()["detail"]
    assert client.get("/api/digests/latest", headers=director).json()["headline"] == "Главное от модели."


def test_p8_p16_the_eval_catches_declined_names_cyrillic_codes_and_counts_abbreviations() -> None:
    case = digest_eval.Case(UUID(int=1), "R01", {}, ["R02", "Ресторан на Арбате"])
    good = {"headline": "Фудкост вырос на 0,5 п.п. за месяц. Начните с закупки.", "items": {}}
    assert digest_eval.check(case, good).ok
    leak = digest_eval.check(case, {"headline": "Как в ресторане на арбате.", "items": {}})
    assert leak.leak and not leak.ok
    assert digest_eval.check(case, {"headline": "Как у r02.", "items": {}}).leak
    assert not digest_eval.check(case, {"headline": "Это видно по М1.", "items": {}}).ok  # Cyrillic «М»


def test_p10_the_same_product_in_two_restaurants_is_two_objects() -> None:
    def fw(key: str) -> Any:
        return SimpleNamespace(finding=SimpleNamespace(key=key, id=UUID(int=0)))

    assert builder._object(fw("M4:R01:paper")) != builder._object(fw("M4:R02:paper"))
    assert builder._object(fw("M3:R01:P05")) == builder._object(fw("M3:R01:P05:contract"))


def test_p12_empty_texts_are_not_an_answer() -> None:
    schema = strict_schema(digest_writer.Texts.model_json_schema())
    assert schema["properties"]["headline"]["minLength"] == 1
    assert schema["$defs"]["ItemText"]["properties"]["text"]["minLength"] == 1


@pytest.mark.usefixtures("demo")
def test_p13_the_weeks_tasks_come_in_one_order(network: Network, owner_engine: Engine) -> None:
    r01 = _r(owner_engine, network, "R01")
    with Session(owner_engine) as s, s.begin():
        for title in ("Б задача", "А задача"):
            s.add(
                Task(
                    tenant_id=network.a.id,
                    restaurant_id=r01,
                    assigned_by="hq",
                    title=title,
                    checklist=[],
                    checklist_done=[],
                    created_on=WEEK.start,
                    due_on=WEEK.end,
                    status=TaskStatus.DONE,
                    done_on=WEEK.end,
                )
            )
    admin = _ctx(network, "admin@a.ru", owner_engine)
    tasks = _digest(owner_engine, _assemble(admin, r01)).input["improved"]["tasks"]
    assert tasks[:2] == ["А задача", "Б задача"]


@pytest.mark.usefixtures("demo")
def test_p15_disagree_twice_at_once_and_only_with_an_item_of_that_digest(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    director = login(client, "r01@a.ru")
    digest = client.post("/api/digests/rebuild", json={}, headers=director).json()
    item = digest["problems"][0]
    url = f"/api/findings/{item['finding_id']}/disagree"
    body = {"reason": "explained", "comment": "Банкет", "digest_id": digest["id"]}
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda _: client.post(url, json=body, headers=director).status_code, range(2)))
    assert codes == [204, 204]
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Disagreement)).scalar_one() == 1
    # The comment comes back with the reason, so changing the reason keeps it.
    again = client.get("/api/digests/latest", headers=director).json()["problems"][0]
    assert (again["disagreed"], again["disagreed_comment"]) == ("explained", "Банкет")
    # A digest that does not hold this item is no digest for the reaction.
    other = client.post("/api/digests/rebuild", json={}, headers=login(client, "admin@a.ru")).json()
    if item["finding_id"] not in {i["finding_id"] for i in other["problems"] + other["opportunities"]}:
        r = client.post(url, json={**body, "digest_id": other["id"]}, headers=director)
        assert r.status_code == 404


@pytest.mark.usefixtures("demo")
def test_p14_the_hq_reads_one_restaurants_disagreements(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    director, admin = login(client, "r01@a.ru"), login(client, "admin@a.ru")
    item = client.post("/api/digests/rebuild", json={}, headers=director).json()["problems"][0]
    client.post(
        f"/api/findings/{item['finding_id']}/disagree", json={"reason": "wrong_data"}, headers=director
    )
    r01, r02 = _r(owner_engine, network, "R01"), _r(owner_engine, network, "R02")
    assert len(client.get(f"/api/digests/disagreements?restaurant_id={r01}", headers=admin).json()) == 1
    assert client.get(f"/api/digests/disagreements?restaurant_id={r02}", headers=admin).json() == []


@pytest.mark.usefixtures("demo")
def test_p17_the_monday_runs_catch_up_only_what_is_missing(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = next(j for j in worker.cron_jobs() if j.name == "cron:weekly_digests")
    assert job.weekday == {0} and job.hour == set(range(5, 12)) and job.minute == {31}
    admin = _ctx(network, "admin@a.ru", owner_engine)
    _assemble(admin, None)  # the network's is there already
    first = weekly.run(network.a.id, TODAY, only_missing=True)
    with Session(owner_engine) as s:
        built = s.execute(
            select(func.count()).select_from(Digest).where(Digest.tenant_id == network.a.id)
        ).scalar_one()
        places = s.execute(
            select(func.count()).select_from(Restaurant).where(Restaurant.tenant_id == network.a.id)
        ).scalar_one()
    # Every restaurant got one — the upsert matched its index also once psycopg prepared the statement.
    assert first == places and built == places + 1
    assert weekly.run(network.a.id, TODAY, only_missing=True) == 0


@pytest.mark.usefixtures("demo")
def test_items_carry_the_effect_and_a_first_step(client: TestClient) -> None:
    """Frontend review p. 9: the task dialog gets the effect from the server and never invents a step."""
    item = client.post("/api/digests/rebuild", json={}, headers=login(client, "r01@a.ru")).json()["problems"][
        0
    ]
    assert item["effect_rub_month"] is not None and item["actions"]


@pytest.mark.usefixtures("demo")
def test_a_stock_out_among_the_problems_is_not_repeated_in_the_risks(
    network: Network, owner_engine: Engine
) -> None:
    """Test pass 03.11.2026: an M6 problem could be both a problem and a risk of one digest."""
    weekly.run(network.a.id, TODAY)
    with Session(owner_engine) as s:
        digests = s.execute(select(Digest).where(Digest.tenant_id == network.a.id)).scalars().all()
        for d in digests:
            problems = {i["finding_id"] for i in d.input["problems"]}
            assert problems.isdisjoint(i["finding_id"] for i in d.input["risks"]), d.restaurant_id
