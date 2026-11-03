"""Stage 6 end-of-stage pass (03.11.2026, after the code review): requirements of docs/08 part 1 that had no
test — every digest endpoint walked for another restaurant and another network, the rebuild within a
director's daily budget, a restaurant without findings, the 3–5 rule with fewer items, and texts by rules
that never state a figure the digest does not hold (TC-DG-32…)."""

import json
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.ai import digest_writer
from app.ai.evals import digest as digest_eval
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.ai.models import AiRun
from app.core.period import get_today
from app.digests import builder, texts, weekly
from app.digests.models import Digest, Disagreement
from app.insights.models import Finding
from app.main import app
from app.overview.service import CONFIDENCE_WEIGHT
from app.tenancy.models import Restaurant
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)

WEEK = builder.Week.before(TODAY)


@pytest.fixture
def today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _finding(
    tenant_id: UUID, restaurant_id: UUID, code: str, title: str, effect: str = "12000.00"
) -> Finding:
    return Finding(
        tenant_id=tenant_id,
        restaurant_id=restaurant_id,
        kind="problem",
        process="production",
        title=title,
        effect_rub_month=Decimal(effect),
        actions=["Проверить порционирование"],
        found_on=TODAY,
        key=f"M1:{code}:P01",
        module="M1",
        confidence="high",
    )


def _rules_pass_the_check(data: dict[str, Any], out: dict[str, Any]) -> list[str]:
    """The texts by rules, through the very check the model's texts go through (`digest_writer.strictly`)."""
    t = digest_writer.Texts(
        headline=out["headline"],
        items=[digest_writer.ItemText(finding_id=k, text=v) for k, v in out["items"].items()],
    )
    return digest_writer.strictly(t, data)


# ------------------------------------------------------------------ the 3–5 rule (unit)


def _fw(kind: str, key: str) -> Any:
    return SimpleNamespace(finding=SimpleNamespace(kind=kind, key=key, id=UUID(int=hash(key) % 2**64)))


def test_fewer_than_three_items_are_shown_as_they_are_and_never_more_than_five() -> None:
    """docs/08 «Правило отбора»: 3–5 with the largest effect × confidence; fewer than 3 — as many as there
    are, without padding; a problem and an opportunity on one object are not both shown."""
    two = [_fw("problem", "M1:R01:P01"), _fw("problem", "M3:R01:P02")]
    assert builder._pick(two, "problem", set()) == two  # 2 — not padded to 3
    assert builder._pick([], "problem", set()) == []
    seven = [_fw("problem", f"M1:R01:P{n:02}") for n in range(7)]
    assert builder._pick(seven, "problem", set()) == seven[:5]  # the 5 ranked first
    taken: set[str] = set()
    problems = builder._pick([_fw("problem", "M5:R01:P01")], "problem", taken)
    same = [_fw("opportunity", "M3:R01:P01:best_price"), _fw("opportunity", "M3:R01:P09")]
    assert builder._pick(same, "opportunity", taken) == same[1:]  # P01 is the problem's already
    assert len(problems) == 1


def test_the_rules_headline_of_a_quiet_week_names_no_figure() -> None:
    quiet = {
        "on_table": {"losses": "0 ₽", "potential": "0 ₽", "total": "0 ₽"},
        "problems": [],
        "opportunities": [],
        "risks": [],
        "processes": [{"title": "Закупка", "status": "good"}],
        "improved": {"tasks_done": 0},
    }
    assert texts.headline(quiet) == "Открытых проблем с оценкой в рублях нет."


# ------------------------------------------------------------------ a restaurant without findings


def test_a_directors_digest_when_the_restaurant_has_no_findings(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """A1 has no data at all: every process «норма» 100, no items, nothing «на столе», and the texts by rules
    state no figure (no «None ₽») — the digest is still built and readable."""
    built = weekly.run(network.a.id, TODAY)
    assert built == len(network.a.restaurants) + 1  # 3 restaurants and the network
    shown = client.get("/api/digests/latest", headers=login(client, "director1@a.ru"))
    assert shown.status_code == 200, shown.text
    d = shown.json()
    assert d["restaurant_id"] == str(network.a.restaurants["A1"]) and d["source"] == "rules"
    assert [(p["index"], p["status"], p["change"]) for p in d["processes"]] == [(100, "good", None)] * 8
    assert d["problems"] == d["opportunities"] == d["risks"] == []
    assert d["on_table"] == {"losses": "0 ₽", "potential": "0 ₽", "total": "0 ₽"}
    assert d["improved"]["tasks_done"] == 0 and d["kpis"] is None and d["last_count"] is None
    assert d["headline"] == "Открытых проблем с оценкой в рублях нет."
    assert "None" not in json.dumps(d, ensure_ascii=False)
    with Session(owner_engine) as s:
        row = s.execute(
            select(Digest).where(Digest.restaurant_id == network.a.restaurants["A1"])
        ).scalar_one()
    assert _rules_pass_the_check(row.input, row.output) == []


# ------------------------------------------------------------------ isolation of every digest endpoint


@pytest.mark.usefixtures("today")
def test_every_digest_endpoint_keeps_to_the_readers_restaurant_and_network(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """CLAUDE.md p. 2: each stage-6 endpoint with another restaurant (a director) and another network (HQ and
    director). Another restaurant's or network's digest answers like a missing one; the archive is empty."""
    a, b = network.a, network.b
    a1, a2, b1 = a.restaurants["A1"], a.restaurants["A2"], b.restaurants["B1"]
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        mine = _finding(a.id, a1, "A1", "Перерасход сыра A1")
        theirs = _finding(a.id, a2, "A2", "Перерасход сыра A2")
        foreign = _finding(b.id, b1, "B1", "Перерасход сыра сети Б")
        s.add_all([mine, theirs, foreign])
    weekly.run(a.id, TODAY)
    weekly.run(b.id, TODAY)
    with Session(owner_engine) as s:
        rows = s.execute(select(Digest.id, Digest.restaurant_id, Digest.tenant_id)).all()
    digest_of = {r: i for i, r, t in rows if t == a.id or r is not None}  # A's network digest under None

    director, director2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    admin, admin_b = login(client, "admin@a.ru"), login(client, "admin@b.ru")
    director_b = login(client, "director1@b.ru")

    # GET /digests/latest and /digests/weeks: another restaurant or network — 404 and an empty archive.
    for who, place in ((director, a2), (director, b1), (admin, b1), (director_b, a1)):
        assert client.get(f"/api/digests/latest?restaurant_id={place}", headers=who).status_code == 404
        r = client.get(f"/api/digests/weeks?restaurant_id={place}", headers=who)
        assert r.status_code == 200 and r.json() == []
        week = f"/api/digests/latest?restaurant_id={place}&week_start={WEEK.start}"
        assert client.get(week, headers=who).status_code == 404
    for who in (director, director_b):  # a director never gets the network's digest by naming no restaurant
        assert client.get("/api/digests/latest", headers=who).json()["scope"] == "restaurant"
    own = client.get("/api/digests/latest", headers=director).json()
    assert own["restaurant_id"] == str(a1)
    assert [i["title"] for i in own["problems"]] == ["Перерасход сыра A1"]
    net = client.get("/api/digests/latest", headers=admin).json()
    assert net["restaurants_count"] == 3 and "сети Б" not in json.dumps(net, ensure_ascii=False)
    assert client.get("/api/digests/latest", headers=admin_b).json()["restaurants_count"] == 1

    # POST /digests/rebuild: another restaurant (director), another network (HQ, director) — 404, none built.
    for who, place in ((director, a2), (director, b1), (admin, b1), (director_b, a1)):
        r = client.post("/api/digests/rebuild", json={"restaurant_id": str(place)}, headers=who)
        assert r.status_code == 404, r.text
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Digest)).scalar_one() == len(rows)

    # POST /findings/{id}/disagree: the digest named must be the reader's own and hold the item.
    url = f"/api/findings/{mine.id}/disagree"
    for other in (digest_of[a2], digest_of[b1], digest_of[None]):
        r = client.post(url, json={"reason": "wrong_data", "digest_id": str(other)}, headers=director)
        assert r.status_code == 404, r.text
    for fid in (theirs.id, foreign.id):  # another restaurant's / network's finding
        r = client.post(f"/api/findings/{fid}/disagree", json={"reason": "wrong_data"}, headers=director)
        assert r.status_code == 404
    body = {"reason": "explained", "comment": "Банкет", "digest_id": str(digest_of[a1])}
    assert client.post(url, json=body, headers=director).status_code == 204

    # DELETE /findings/{id}/disagree: another director cannot withdraw it; it stays.
    assert client.delete(url, headers=director2).status_code == 404
    assert client.delete(url, headers=director_b).status_code == 404

    # GET /digests/disagreements: the HQ of this network only, of a named restaurant only.
    assert [d["finding_title"] for d in client.get("/api/digests/disagreements", headers=admin).json()] == [
        "Перерасход сыра A1"
    ]
    assert client.get("/api/digests/disagreements", headers=admin_b).json() == []
    other_net = client.get(f"/api/digests/disagreements?restaurant_id={a1}", headers=admin_b)
    assert other_net.status_code in (200, 404) and "Перерасход" not in other_net.text
    assert client.get(f"/api/digests/disagreements?restaurant_id={b1}", headers=admin).json() == []
    for who in (director, director2, director_b):
        assert client.get("/api/digests/disagreements", headers=who).status_code == 403
    analyst = login(client, "analyst@a.ru")
    assert len(client.get("/api/digests/disagreements", headers=analyst).json()) == 1

    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Disagreement)).scalar_one() == 1


# ------------------------------------------------------------------ the rebuild within the budget


def _texts_for_every_item(headline: str) -> Any:
    def reply(request: ModelRequest) -> Reply:
        facts = json.loads(request.messages[0]["content"][0]["text"].split("\n", 1)[1])
        items = facts["problems"] + facts["opportunities"] + facts["risks"]
        body = {
            "headline": headline,
            "items": [{"finding_id": i["finding_id"], "text": "Текст."} for i in items],
        }
        return text_reply(json.dumps(body, ensure_ascii=False))

    return reply


@pytest.mark.usefixtures("today")
def test_a_directors_rebuild_stays_within_their_daily_budget(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """docs/08: «Пересобрать» — the texts by the model within the person's daily budget. Over it the model is
    not called; the digest is by rules if there was no model text, else the model's text stays (409)."""
    a = network.a
    with Session(owner_engine) as s, s.begin():
        s.add(_finding(a.id, a.restaurants["A1"], "A1", "Перерасход сыра"))
    director = login(client, "director1@a.ru")
    fake = FakeModel([_texts_for_every_item("Главное от модели.")])

    def rebuild(per_day: int) -> Any:
        app.dependency_overrides[get_gateway] = lambda: Gateway(fake, per_user_day=per_day)
        try:
            return client.post("/api/digests/rebuild", json={}, headers=director)
        finally:
            app.dependency_overrides.pop(get_gateway, None)

    over = rebuild(0)  # no budget, no model text yet: by rules
    assert over.status_code == 200 and over.json()["source"] == "rules" and fake.requests == []
    assert rebuild(1).json()["source"] == "model" and len(fake.requests) == 1
    with Session(owner_engine) as s:  # the call is the director's, counted against their budget
        runs = s.execute(select(AiRun.user_id, AiRun.task)).all()
    assert runs == [(a.users["director1@a.ru"], "digest")]
    kept = rebuild(1)  # the one call of the day is spent: the model's text stays
    assert kept.status_code == 409 and len(fake.requests) == 1
    assert client.get("/api/digests/latest", headers=director).json()["headline"] == "Главное от модели."


# ------------------------------------------------------------------ on the demo network


@pytest.mark.usefixtures("demo")
def test_every_demo_digest_by_rules_quotes_only_its_figures_one_item_per_object(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """On every digest of the demo network (each restaurant and the network): the texts by rules pass the
    check the model's texts pass (no figure outside the digest); problems and opportunities are ranked by
    effect × confidence, at most 5, one per object (TC-DG-03 asserted it on a key the items do not have);
    risks are M6 only. A director's own rebuild gives the same content as the weekly run (system context)."""
    weekly.run(network.a.id, TODAY)
    with Session(owner_engine) as s:
        digests = s.execute(select(Digest).where(Digest.tenant_id == network.a.id)).scalars().all()
        findings = {str(f.id): f for f in s.execute(select(Finding)).scalars()}
        for d in digests:
            s.expunge(d)
    assert len(digests) > 3
    with Session(owner_engine) as s:
        places = s.execute(select(Restaurant).where(Restaurant.tenant_id == network.a.id)).scalars().all()
    # Codes, and the demo's own names (the fixture's «Сеть А A2» shares the word «Сеть» with every A place).
    names = {o.id: [o.code] + ([] if o.name.startswith("Сеть ") else [o.name]) for o in places}
    others = {p.id: [x for o in places if o.id != p.id for x in names[o.id]] for p in places}
    for d in digests:
        data, where = d.input, d.input["restaurant"] or "network"
        assert d.source == "rules"
        assert _rules_pass_the_check(data, d.output) == [], where
        picked = [findings[i["finding_id"]] for i in data["problems"] + data["opportunities"]]
        objects = [builder._object(cast(Any, SimpleNamespace(finding=f))) for f in picked]
        assert len(objects) == len(set(objects)), where
        for kind in ("problems", "opportunities"):
            block = [findings[i["finding_id"]] for i in data[kind]]
            assert len(block) <= builder.ITEMS_MAX, where
            scores = [
                (f.effect_rub_month or Decimal(0)) * CONFIDENCE_WEIGHT[f.confidence or "medium"]
                for f in block
            ]
            assert scores == sorted(scores, reverse=True), where
        assert all(findings[i["finding_id"]].module == "M6" for i in data["risks"]), where
        if d.restaurant_id is not None:  # a director's digest names no other restaurant, also inside texts
            seen = json.dumps([data, d.output], ensure_ascii=False).replace(data["restaurant"]["name"], "")
            named = [x for x in others[d.restaurant_id] if digest_eval._names(x, seen)]
            assert named == [], (where, named)
    network_digest = next(d for d in digests if d.restaurant_id is None)
    assert len(network_digest.input["problems"]) == builder.ITEMS_MAX  # the demo has more than 5

    r01 = next(d for d in digests if d.input["restaurant"] and d.input["restaurant"]["code"] == "R01")
    mine = client.post("/api/digests/rebuild", json={}, headers=login(client, "r01@a.ru"))
    assert mine.status_code == 200
    with Session(owner_engine) as s:
        again = s.get(Digest, r01.id)
        assert again is not None and again.built_at > r01.built_at
        assert again.input == r01.input  # the same content, whoever built it (idempotent)


# ------------------------------------------------------------------ the index and its trend, by hand


def test_the_index_trend_and_what_improved_worked_out_by_hand(network: Network, owner_engine: Engine) -> None:
    """docs/08 «Индекс процесса»: 100 − 50 × losses / threshold, the threshold × the restaurants for the
    network; the trend is the difference with the previous digest; a process that went up is «улучшилось»."""
    from app.digests import service
    from tests.test_digests import _ctx

    a = network.a
    a1 = a.restaurants["A1"]
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        cheese = _finding(a.id, a1, "A1", "Перерасход сыра", effect="12000.00")
        s.add(cheese)
    admin = _ctx(network, "admin@a.ru", owner_engine)
    first = {r: service.publish(admin, restaurant_id=r, week=WEEK, today=TODAY) for r in (a1, None)}
    with Session(owner_engine) as s:
        mine, net = (s.get(Digest, first[r]) for r in (a1, None))
        assert mine is not None and net is not None
        prod = next(p for p in mine.input["processes"] if p["process"] == "production")
        # A1: 100 − 50 × 12 000 / 25 000 = 100 − 24 = 76 → «внимание» (> 50, < 100)
        assert (prod["index"], prod["status"], prod["change"]) == (76, "warning", None)
        assert prod["losses_per_month"] == "12\xa0000 ₽" and prod["open_problems"] == 1
        # The network of 3 restaurants: threshold 75 000; 100 − 50 × 12 000 / 75 000 = 100 − 8 = 92
        assert next(p for p in net.input["processes"] if p["process"] == "production")["index"] == 92
        assert mine.input["on_table"] == {"losses": "12\xa0000 ₽", "potential": "0 ₽", "total": "12\xa0000 ₽"}
        assert mine.output["headline"] == (
            "На столе 12\xa0000 ₽ в месяц: потери 12\xa0000 ₽, потенциал 0 ₽. "
            "Главное — «Перерасход сыра»: 12\xa0000 ₽ в месяц."
        )
    with Session(owner_engine) as s, s.begin():  # solved during the week
        s.execute(update(Finding).where(Finding.id == cheese.id).values(status="resolved"))
    nxt = builder.Week(WEEK.start + timedelta(days=7), WEEK.end + timedelta(days=7))
    later = service.publish(admin, restaurant_id=a1, week=nxt, today=TODAY)
    with Session(owner_engine) as s:
        d = s.get(Digest, later)
        assert d is not None
        prod = next(p for p in d.input["processes"] if p["process"] == "production")
        assert (prod["index"], prod["status"], prod["change"]) == (100, "good", 24)  # 100 − 76 = +24
        assert d.input["improved"]["processes_better"] == ["Производство (ТТК)"]
        assert d.input["kpis_previous_digest"] is None  # the previous had no KPIs either (A1 has no data)


def test_the_digest_eval_target_is_90_percent_and_a_leak_fails_it_whatever_the_score() -> None:
    """docs/08: the goal is ≥ 90 % of digests without remarks and not one leak (TC-DG-21 had one case)."""

    def report(good: int, bad: int, leaks: int = 0) -> Any:
        outcomes = [digest_eval.Outcome(f"R{n}") for n in range(good)]
        outcomes += [digest_eval.Outcome("x", problems=["приветствие"]) for _ in range(bad)]
        outcomes += [digest_eval.Outcome("y", problems=["названы"], leak=True) for _ in range(leaks)]
        return digest_eval.Report(outcomes)

    assert report(9, 1).passed  # 9 / 10 = 90 % — the target itself
    assert not report(8, 2).passed  # 80 %
    assert not report(19, 0, leaks=1).passed  # 95 %, but a leak
    assert not report(0, 0).passed  # nothing measured is no pass


@pytest.mark.parametrize(
    ("done", "said"),
    [
        (1, "За неделю выполнена 1 задача."),
        (2, "За неделю выполнено 2 задачи."),
        (11, "За неделю выполнено 11 задач."),
        (21, "За неделю выполнена 21 задача."),  # agrees with «21 задача», as «1 задача»
    ],
)
def test_the_rules_headline_counts_the_weeks_tasks_in_russian(done: int, said: str) -> None:
    quiet = {
        "on_table": {"losses": "0 ₽", "potential": "0 ₽", "total": "0 ₽"},
        "problems": [],
        "opportunities": [],
        "risks": [],
        "processes": [],
        "improved": {"tasks_done": done},
    }
    assert texts.headline(quiet).endswith(said)


def test_without_problems_the_rules_headline_leads_with_the_best_opportunity() -> None:
    week = {
        "on_table": {"losses": "0 ₽", "potential": "8\xa0000 ₽", "total": "8\xa0000 ₽"},
        "problems": [],
        "opportunities": [{"title": "Лучшая цена сети на сливки", "effect_per_month": "8\xa0000 ₽"}],
        "risks": [],
        "processes": [],
        "improved": {"tasks_done": 0},
    }
    assert texts.headline(week) == (
        "На столе 8\xa0000 ₽ в месяц: потери 0 ₽, потенциал 8\xa0000 ₽. "
        "Главная возможность — «Лучшая цена сети на сливки»: 8\xa0000 ₽ в месяц."
    )


def test_one_failing_digest_does_not_stop_the_weekly_run(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app/digests/weekly.py: a digest that fails is logged, the others are built; the catch-up builds it."""
    from app.digests import service

    a2 = network.a.restaurants["A2"]
    real = service.publish

    def flaky(ctx: Any, *, restaurant_id: UUID | None, **kw: Any) -> UUID:
        if restaurant_id == a2:
            raise RuntimeError("database went away")
        return real(ctx, restaurant_id=restaurant_id, **kw)

    monkeypatch.setattr(service, "publish", flaky)
    assert weekly.run(network.a.id, TODAY) == 3  # A1, A3 and the network; A2 failed
    monkeypatch.setattr(service, "publish", real)
    assert weekly.run(network.a.id, TODAY, only_missing=True) == 1  # the next hourly run builds A2 only
    with Session(owner_engine) as s:
        built = s.execute(select(Digest.restaurant_id).where(Digest.tenant_id == network.a.id)).scalars()
        assert set(built) == {*network.a.restaurants.values(), None}


def test_the_eval_does_not_take_the_restaurants_own_name_for_another_one() -> None:
    """Found 03.11.2026 on the demo network (fixed the same day): R09 «Ресторан на Красном проспекте»,
    another — «Ресторан на Красной». The eval's name match by stem flagged R09's own name in its digest as
    a leak, and one leak fails the whole `make eval-digest` whatever the score (TC-DG-40)."""
    case = digest_eval.Case(
        UUID(int=9),
        "R09",
        {"restaurant": {"code": "R09", "name": "Ресторан на Красном проспекте"}},
        ["R12", "Ресторан на Красной"],
    )
    written = {"headline": "В ресторане на Красном проспекте фудкост в норме.", "items": {}}
    assert not digest_eval.check(case, written).leak
    # The other one, named as it is, is still a leak.
    assert digest_eval.check(case, {"headline": "Как в ресторане на Красной.", "items": {}}).leak
