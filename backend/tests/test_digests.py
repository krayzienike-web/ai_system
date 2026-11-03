"""Weekly digests (docs/08 part 1, stage 6): content by the code, texts by rules, one per scope and week,
seen only by those who may (TC-DG-01…)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session

from app import worker
from app.ai import digest_writer
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.ai.models import AiRun
from app.core.errors import NotFoundError
from app.digests import builder, service, texts, weekly
from app.digests.models import Digest
from app.main import app
from app.tenancy.context import AccessContext, load_access_context, user_session
from app.tenancy.models import Restaurant, User
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)

WEEK = builder.Week.before(TODAY)


def _ctx(network: Network, email: str, owner_engine: Engine) -> AccessContext:
    with Session(owner_engine) as s:
        user_id = s.execute(select(User.id).where(User.email == email)).scalar_one()
    with Session_() as s:
        ctx = load_access_context(s, user_id, network.a.id)
    assert ctx is not None
    return ctx


def Session_() -> Session:
    from app.core.db import get_sessionmaker

    return get_sessionmaker()()


def _r(owner_engine: Engine, network: Network, code: str) -> UUID:
    with Session(owner_engine) as s:
        return s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == code)
        ).scalar_one()


def _assemble(ctx: AccessContext, restaurant_id: UUID | None, week: builder.Week = WEEK, **kw: Any) -> UUID:
    return service.publish(ctx, restaurant_id=restaurant_id, week=week, today=TODAY, **kw)


def test_week_before_is_the_last_full_monday_to_sunday() -> None:
    assert builder.Week.before(date(2026, 11, 2)) == builder.Week(date(2026, 10, 26), date(2026, 11, 1))
    assert builder.Week.before(date(2026, 11, 8)) == builder.Week(date(2026, 10, 26), date(2026, 11, 1))


def test_index_and_status() -> None:
    t = Decimal(100000)
    assert builder.index(builder.ZERO, False, False, t) == 100
    assert builder.index(builder.ZERO, False, True, t) == builder.UNPRICED_INDEX
    assert builder.index(Decimal(50000), True, False, t) == 75
    assert builder.index(Decimal(500000), True, False, t) == 0
    assert builder.index(Decimal(1), True, False, t) == 99  # a priced problem is never «100»
    assert [builder.status(i) for i in (100, 75, 50)] == ["good", "warning", "critical"]


@pytest.mark.usefixtures("demo")
def test_a_digest_is_built_by_the_code_and_written_by_rules(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    digest_id = _assemble(admin, None)
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "rules" and d.prompt_version is None
        data, out = d.input, d.output
    assert data["scope"] == "network" and len(data["processes"]) == 8
    assert builder.ITEMS_MIN <= len(data["problems"]) <= builder.ITEMS_MAX
    from app.insights.models import Finding

    picked = [UUID(i["finding_id"]) for i in data["problems"] + data["opportunities"]]
    with Session(owner_engine) as s:  # the items carry no object: it is the finding's key («M1:R01:P01»)
        keys = s.execute(select(Finding.key).where(Finding.id.in_(picked))).scalars().all()
    objects = [":".join(k.split(":")[1:3]) for k in keys if k]
    assert len(keys) == len(picked) and len(objects) == len(set(objects))  # one item per object
    assert out == texts.by_rules(data)
    assert data["problems"][0]["title"] in out["headline"]
    assert set(out["items"]) == {
        i["finding_id"] for i in data["problems"] + data["opportunities"] + data["risks"]
    }


@pytest.mark.usefixtures("demo")
def test_building_again_replaces_and_the_next_week_compares(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    first = _assemble(admin, None)
    assert _assemble(admin, None) == first  # idempotent: one per week
    nxt = builder.Week(timedelta(7) + WEEK.start, timedelta(7) + WEEK.end)
    _assemble(admin, None, nxt)
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Digest)).scalar_one() == 2
        later = s.execute(select(Digest).where(Digest.week_start == nxt.start)).scalar_one()
    assert later.input["kpis_previous_digest"] is not None
    assert all(p["change"] is not None for p in later.input["processes"])


@pytest.mark.usefixtures("demo")
def test_a_model_writer_is_used_and_its_absence_falls_back(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    seen: list[dict[str, Any]] = []

    def write(data: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
        seen.append(data)
        return ({"headline": "Текст модели", "items": {}}, 1) if len(seen) == 1 else None

    digest_id = _assemble(admin, None, write=write)
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and (d.source, d.prompt_version, d.output["headline"]) == (
            "model",
            1,
            "Текст модели",
        )
    _assemble(admin, None, write=write)  # the model's text did not pass: rules
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "rules" and d.prompt_version is None


@pytest.mark.usefixtures("demo")
def test_a_director_sees_only_their_restaurants_digest(network: Network, owner_engine: Engine) -> None:
    admin, director = _ctx(network, "admin@a.ru", owner_engine), _ctx(network, "r01@a.ru", owner_engine)
    r01, r02 = _r(owner_engine, network, "R01"), _r(owner_engine, network, "R02")
    for scope in (None, r01, r02):
        _assemble(admin, scope)
    with user_session(director) as s:
        mine = service.latest(s, r01)
        assert (
            mine.input["scope"] == "restaurant"
            and mine.restaurant_id == r01
            and mine.input["restaurant"]["code"] == "R01"
        )
        assert "restaurants" not in mine.input  # no per-restaurant table for a director
        for other in (r02, None):
            with pytest.raises(NotFoundError):
                service.latest(s, other)
        assert service.weeks(s, None) == []
    with user_session(admin) as s:
        assert len(service.weeks(s, None)) == 1


@pytest.mark.usefixtures("demo")
def test_a_restaurants_digest_holds_only_reviewed_findings_of_it(
    network: Network, owner_engine: Engine
) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    r01 = _r(owner_engine, network, "R01")
    digest_id = _assemble(admin, r01)
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None
        ids = [i["finding_id"] for i in d.input["problems"] + d.input["opportunities"] + d.input["risks"]]
        from app.insights.models import Finding

        rows = s.execute(
            select(Finding.restaurant_id, Finding.review_status).where(Finding.id.in_(ids))
        ).all()
    assert rows and all(r == r01 and st in (None, "confirmed") for r, st in rows)


# ------------------------------------------------------------------ the model's texts (step 3)


def _model_texts(headline: str, data_of: Any, item: str = "Текст пункта") -> Any:
    """A scripted answer naming every item of the digest the model was given."""

    def reply(request: ModelRequest) -> Reply:
        facts = json.loads(request.messages[0]["content"][0]["text"].split("\n", 1)[1])
        data_of.append(facts)
        ids = [i["finding_id"] for i in facts["problems"] + facts["opportunities"] + facts["risks"]]
        body = {"headline": headline, "items": [{"finding_id": i, "text": item} for i in ids]}
        return text_reply(json.dumps(body, ensure_ascii=False))

    return reply


@pytest.mark.usefixtures("demo")
def test_the_models_texts_quote_only_the_digests_numbers(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    fake, seen = FakeModel(), []  # type: ignore[var-annotated]
    fake.replies += [_model_texts("Главное: проверить закупки.", seen)]
    digest_id = _assemble(admin, None, write=digest_writer.writer(Gateway(fake), admin))
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "model" and d.prompt_version == 2
        assert d.output["headline"] == "Главное: проверить закупки."
        assert set(d.output["items"].values()) == {"Текст пункта"}
        total = d.input["on_table"]["total"]
    # A number not in the facts: corrected once; still wrong — the rules write.
    fake.replies += [_model_texts("На столе 999 999 ₽.", seen), _model_texts("На столе 999 999 ₽.", seen)]
    _assemble(admin, None, write=digest_writer.writer(Gateway(fake), admin))
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "rules"
    # The figure from the facts passes.
    fake.replies += [_model_texts(f"На столе {total} в месяц.", seen)]
    _assemble(admin, None, write=digest_writer.writer(Gateway(fake), admin))
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "model"


@pytest.mark.usefixtures("demo")
def test_the_model_must_write_exactly_the_digests_items(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    missing = text_reply(json.dumps({"headline": "Главное.", "items": []}, ensure_ascii=False))
    fake = FakeModel([missing, missing])
    digest_id = _assemble(admin, None, write=digest_writer.writer(Gateway(fake), admin))
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "rules"
    assert len(fake.requests) == 2  # asked to correct once


@pytest.mark.usefixtures("demo")
def test_an_unreachable_model_leaves_the_rules(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    digest_id = _assemble(admin, None, write=digest_writer.writer(Gateway(FakeModel()), admin))  # no reply
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None and d.source == "rules"
    over = digest_writer.writer(Gateway(FakeModel([text_reply("{}")]), per_user_day=0), admin)
    assert _assemble(admin, None, write=over) == digest_id


@pytest.mark.usefixtures("demo")
def test_a_directors_digest_tells_the_model_nothing_of_other_restaurants(
    network: Network, owner_engine: Engine
) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    r01 = _r(owner_engine, network, "R01")
    fake, seen = FakeModel(), []  # type: ignore[var-annotated]
    fake.replies += [_model_texts("Главное.", seen)]
    _assemble(admin, r01, write=digest_writer.writer(Gateway(fake), admin))
    with Session(owner_engine) as s:
        others = s.execute(
            select(Restaurant.code).where(Restaurant.tenant_id == network.a.id, Restaurant.id != r01)
        ).scalars()
        sent = json.dumps(seen[0], ensure_ascii=False)
        assert not [c for c in others if f'"{c}"' in sent]


# ------------------------------------------------------------------ the weekly run (step 4)


def test_the_digests_are_scheduled_on_monday_morning_in_moscow() -> None:
    job = next(j for j in worker.cron_jobs() if j.name == "cron:weekly_digests")
    assert isinstance(job.hour, set)
    assert (job.weekday, min(job.hour), job.minute) == ({0}, 5, {31})  # 08:31 Moscow (Q24), then catch-ups


@pytest.mark.usefixtures("demo")
def test_the_weekly_run_builds_every_restaurant_and_the_network(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(weekly.tenants()) == {network.a.id, network.b.id}  # ids only, past the tenants' row security
    fake = FakeModel([_model_texts("Главное.", []) for _ in range(30)])
    monkeypatch.setattr(worker, "get_gateway", lambda: Gateway(fake))
    built = worker.build_digests(TODAY)
    with Session(owner_engine) as s:
        a = s.execute(
            select(func.count()).select_from(Restaurant).where(Restaurant.tenant_id == network.a.id)
        )
        restaurants_a = a.scalar_one()
        rows = s.execute(select(Digest.tenant_id, Digest.restaurant_id, Digest.source)).all()
        runs = s.execute(select(AiRun.user_id, AiRun.task).where(AiRun.tenant_id == network.a.id)).all()
    mine = [r for r in rows if r.tenant_id == network.a.id]
    assert len(mine) == restaurants_a + 1 and built == len(rows)
    assert {r.source for r in mine} == {"model"} and sum(r.restaurant_id is None for r in mine) == 1
    # The model's calls of background work are logged without a person and no person reads them.
    assert runs and all(u is None and t == "digest" for u, t in runs)
    admin = _ctx(network, "admin@a.ru", owner_engine)
    with user_session(admin) as s:
        assert s.execute(select(func.count()).select_from(AiRun)).scalar_one() == 0
    assert worker.build_digests(TODAY) == 0  # a catch-up run: everything is there, nothing is built again
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Digest)).scalar_one() == len(rows)


@pytest.mark.usefixtures("demo")
def test_without_the_model_the_weekly_run_writes_by_rules(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "get_gateway", lambda: None)
    assert weekly.run(network.a.id, TODAY) > 0
    with Session(owner_engine) as s:
        assert set(s.execute(select(Digest.source)).scalars()) == {"rules"}


# ------------------------------------------------------------------ the API


@pytest.fixture
def model() -> Any:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


@pytest.mark.usefixtures("demo")
def test_the_digest_screens_read_what_was_built(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    admin, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    assert client.get("/api/digests/latest", headers=director).status_code == 404  # none yet
    built = client.post("/api/digests/rebuild", json={}, headers=director)
    assert built.status_code == 200, built.text
    mine = built.json()
    assert (
        mine["scope"] == "restaurant" and mine["restaurant"].startswith("R01") and mine["source"] == "rules"
    )
    assert mine["week_start"] == str(WEEK.start) and mine["headline"]
    assert all(i["text"] for i in mine["problems"] + mine["opportunities"] + mine["risks"])
    assert client.get("/api/digests/latest", headers=director).json()["id"] == mine["id"]
    assert client.get("/api/digests/weeks", headers=director).json() == [
        {"week_start": str(WEEK.start), "week_end": str(WEEK.end)}
    ]
    # The network's digest: built and read by the HQ only.
    net = client.post("/api/digests/rebuild", json={}, headers=admin).json()
    assert net["scope"] == "network" and net["restaurants_count"] > 1
    r02 = str(_r(owner_engine, network, "R02"))
    for url in ("/api/digests/latest?restaurant_id=" + r02, "/api/digests/latest?week_start=2020-01-06"):
        assert client.get(url, headers=director).status_code == 404
    assert (
        client.post("/api/digests/rebuild", json={"restaurant_id": r02}, headers=director).status_code == 404
    )
    assert client.get("/api/digests/latest", headers=admin).json()["id"] == net["id"]
    r01 = mine["restaurant_id"]
    assert client.get(f"/api/digests/latest?restaurant_id={r01}", headers=admin).json()["id"] == mine["id"]


@pytest.mark.usefixtures("demo")
def test_the_rebuild_button_writes_by_the_model_when_it_is_on(client: TestClient, model: FakeModel) -> None:
    director = login(client, "r01@a.ru")
    model.replies += [_model_texts("Главное от модели.", [])]
    out = client.post("/api/digests/rebuild", json={}, headers=director).json()
    assert out["source"] == "model" and out["headline"] == "Главное от модели."
    assert {i["text"] for i in out["problems"]} == {"Текст пункта"}


# ------------------------------------------------------------------ the director's reactions (step 5)


def _first_item(client: TestClient, headers: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    digest = client.post("/api/digests/rebuild", json={}, headers=headers).json()
    return digest, (digest["problems"] + digest["opportunities"])[0]


@pytest.mark.usefixtures("demo")
def test_take_it_on_is_a_task_to_oneself_shown_in_the_digest(
    client: TestClient, owner_engine: Engine
) -> None:
    from app.insights.models import Finding
    from app.tasks.models import Task

    director = login(client, "r01@a.ru")
    _, item = _first_item(client, director)
    with Session(owner_engine) as s, s.begin():  # the demo took it already: free it, as on a new week
        s.execute(delete(Task).where(Task.finding_id == UUID(item["finding_id"])))
        s.execute(update(Finding).where(Finding.id == UUID(item["finding_id"])).values(status="new"))
    digest, item = _first_item(client, director)
    assert not item["taken"]
    due = str(TODAY + timedelta(days=7))
    made = client.post(
        "/api/tasks",
        json={"title": item["title"], "due_on": due, "finding_id": item["finding_id"]},
        headers=director,
    )
    assert made.status_code == 201, made.text
    assert made.json()[0]["restaurant_id"] == digest["restaurant_id"]  # for their own restaurant
    again = client.get("/api/digests/latest", headers=director).json()
    assert next(
        i for i in again["problems"] + again["opportunities"] if i["finding_id"] == item["finding_id"]
    )["taken"]


@pytest.mark.usefixtures("demo")
def test_disagree_with_a_reason_reaches_the_hq(client: TestClient) -> None:
    admin, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    digest, item = _first_item(client, director)
    url = f"/api/findings/{item['finding_id']}/disagree"
    reasons = client.get("/api/digests/disagree-reasons", headers=director).json()
    assert {r["reason"] for r in reasons} == {"wrong_data", "explained", "already_fixed", "other"}
    assert client.post(url, json={"reason": "other"}, headers=director).status_code == 422  # say what
    assert client.post(url, json={"reason": "nope"}, headers=director).status_code == 422
    body = {"reason": "explained", "comment": "Был банкет", "digest_id": digest["id"]}
    assert client.post(url, json=body, headers=director).status_code == 204
    assert client.post(url, json={**body, "comment": "Банкет 30.10"}, headers=director).status_code == 204
    shown = client.get("/api/digests/latest", headers=director).json()
    assert (
        next(i for i in shown["problems"] + shown["opportunities"] if i["finding_id"] == item["finding_id"])[
            "disagreed"
        ]
        == "explained"
    )
    (row,) = client.get("/api/digests/disagreements", headers=admin).json()  # replaced, not added
    assert row["comment"] == "Банкет 30.10" and row["restaurant"].startswith("R01")
    assert row["reason_title"].startswith("Есть объяснение")
    assert client.get("/api/digests/disagreements", headers=director).status_code == 403
    assert (
        client.post(url, json=body, headers=admin).status_code == 403
    )  # the HQ reviews, it does not disagree
    assert client.delete(url, headers=director).status_code == 204
    assert client.delete(url, headers=director).status_code == 404
    assert client.get("/api/digests/disagreements", headers=admin).json() == []


@pytest.mark.usefixtures("demo")
def test_a_director_cannot_disagree_with_another_restaurants_finding(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    from app.insights.models import Finding

    r02 = _r(owner_engine, network, "R02")
    with Session(owner_engine) as s:
        other = s.execute(select(Finding.id).where(Finding.restaurant_id == r02).limit(1)).scalar_one()
        pending = s.execute(
            select(Finding.id)
            .where(Finding.tenant_id == network.a.id, Finding.review_status == "pending")
            .limit(1)
        ).scalar_one()
    director = login(client, "r01@a.ru")
    for fid in (other, pending):
        r = client.post(f"/api/findings/{fid}/disagree", json={"reason": "wrong_data"}, headers=director)
        assert r.status_code == 404, r.text
