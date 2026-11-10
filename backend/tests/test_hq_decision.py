"""ADR 0009, stage 6.1: a finding reaches a director only through the HQ's decision — review → «Ждут решения»
(«Решить по находке») → a task on the director's restaurant (TC-WORK-06…17, TC-REV-09)."""

import json
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, true
from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.gateway import FakeModel, Gateway, get_gateway, text_reply
from app.core.security import hash_password
from app.digests import builder, service
from app.digests.models import Digest
from app.insights.models import Finding
from app.main import app
from app.tasks.models import Task
from app.tenancy.models import Restaurant, Role, RoleAssignment, User
from tests.conftest import PASSWORD, Network, hq_task, login
from tests.test_digests import _ctx
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


def _untasked(
    owner_engine: Engine, network: Network, code: str = "R01", *, measured: bool = False
) -> UUID | None:
    """A reviewed open finding of the restaurant with no task yet (`measured`: one a check can measure)."""
    with Session(owner_engine) as s:
        rid = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == code)
        ).scalar_one()
        tasked = select(Task.finding_id).where(Task.finding_id.is_not(None))
        return (
            s.execute(
                select(Finding.id).where(
                    Finding.restaurant_id == rid,
                    Finding.status == "new",
                    Finding.review_status.is_distinct_from("pending"),
                    Finding.review_status.is_distinct_from("rejected"),
                    Finding.id.not_in(tasked),
                    Finding.module.in_(("M1", "M3", "M5", "M6", "M8")) if measured else true(),
                )
            )
            .scalars()
            .first()
        )


def _seen_by_director(
    client: TestClient, headers: dict[str, str], fid: UUID, owner_engine: Engine, network: Network
) -> list[str]:
    """Every place a director could meet the finding: card, lists, board, week, chat tools, digest."""
    where = []
    if client.get(f"/api/findings/{fid}", headers=headers).status_code == 200:
        where.append("card")
    for path in ("/api/findings", "/api/overview/findings", "/api/overview/restaurants/R01", "/api/tasks"):
        if str(fid) in client.get(path, headers=headers).text:
            where.append(path)
    with Session(owner_engine) as s:
        user = s.execute(select(User.id).where(User.email == "r01@a.ru")).scalar_one()
    for name, args in (("get_findings", {}), ("explain_finding", {"finding_id": str(fid)})):
        result, _ = tools.run(name, args, user_id=user, tenant_id=network.a.id, today=TODAY)
        if str(fid) in str(result) and "error" not in result:
            where.append(f"tool {name}")
    digest = client.post("/api/digests/rebuild", json={}, headers=headers).json()
    if str(fid) in str(digest):
        where.append("digest")
    return where


@pytest.mark.usefixtures("demo")
def test_a_director_meets_a_finding_only_once_the_hq_set_a_task(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    fid = _untasked(owner_engine, network)
    assert fid is not None
    director, admin = login(client, "r01@a.ru"), login(client, "admin@a.ru")
    assert _seen_by_director(client, director, fid, owner_engine, network) == []
    # It waits for the HQ's decision.
    assert str(fid) in client.get("/api/overview/awaiting", headers=admin).text
    # The director cannot take it on themselves.
    due = str(TODAY + timedelta(days=3))
    r = client.post(
        "/api/tasks", json={"title": "x", "due_on": due, "finding_id": str(fid)}, headers=director
    )
    assert r.status_code in (403, 404)
    # The HQ puts a task on the restaurant: now the director meets it everywhere, and it leaves the list.
    made = client.post(
        "/api/tasks", json={"title": "Шаг 1", "due_on": due, "finding_id": str(fid)}, headers=admin
    )
    assert made.status_code == 201, made.text
    seen = _seen_by_director(client, director, fid, owner_engine, network)
    assert {"card", "/api/findings", "/api/tasks", "tool explain_finding"} <= set(seen)
    assert str(fid) not in client.get("/api/overview/awaiting", headers=admin).text


@pytest.mark.usefixtures("demo")
def test_awaiting_holds_restaurants_and_network_findings_and_is_the_hqs(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    admin, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    awaiting = client.get("/api/overview/awaiting", headers=admin).json()
    assert awaiting and all(
        f["work"]["stage"] == "new" and not f["work"]["check_waiting_launch"] for f in awaiting
    )
    assert any(f["restaurant_id"] is None for f in awaiting) and any(f["restaurant_id"] for f in awaiting)
    assert all(f["review_status"] in (None, "confirmed") for f in awaiting)
    # by money × confidence, the most valuable first (overview.rank)
    weight = {"high": 1.0, "medium": 0.7, "low": 0.4}
    efforts = [
        float(f["effect_rub_month"]) * weight[f["confidence"] or "medium"]
        for f in awaiting
        if f["effect_rub_month"]
    ]
    assert efforts == sorted(efforts, reverse=True) or len(efforts) < 2
    assert client.get("/api/overview/awaiting", headers=director).status_code == 403
    # The badge counts them with the checks to launch and the late tasks.
    badge = client.get("/api/overview/badges", headers=admin).json()["inbox"]
    checks = len(client.get("/api/checks?status=proposed", headers=admin).json())
    late = len(client.get("/api/tasks?late=true", headers=admin).json())
    assert badge == len(awaiting) + checks + late


@pytest.mark.usefixtures("demo")
def test_a_directors_own_task_without_a_finding_is_still_theirs(client: TestClient) -> None:
    director = login(client, "r01@a.ru")
    due = str(TODAY + timedelta(days=3))
    r = client.post("/api/tasks", json={"title": "Проверить холодильник", "due_on": due}, headers=director)
    assert r.status_code == 201 and r.json()[0]["assigned_by"] == "director"


@pytest.mark.usefixtures("demo")
def test_a_directors_digest_holds_only_findings_with_a_task(network: Network, owner_engine: Engine) -> None:
    admin = _ctx(network, "admin@a.ru", owner_engine)
    with Session(owner_engine) as s:
        r01 = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == "R01")
        ).scalar_one()
        tasked = {
            f for f in s.execute(select(Task.finding_id).where(Task.restaurant_id == r01)).scalars() if f
        }
    digest_id = service.publish(admin, restaurant_id=r01, week=builder.Week.before(TODAY), today=TODAY)
    with Session(owner_engine) as s:
        d = s.get(Digest, digest_id)
        assert d is not None
        items = [UUID(i["finding_id"]) for k in ("problems", "opportunities", "risks") for i in d.input[k]]
    assert set(items) <= tasked


@pytest.mark.usefixtures("demo")
def test_the_week_does_not_tell_a_director_how_much_unassigned_findings_grew(client: TestClient) -> None:
    """The stored weekly totals count every reviewed finding, also those without a task: a director gets no
    «за неделю потенциал вырос на …» from them (ADR 0009); the HQ still does."""
    director = client.get("/api/overview/restaurants/R01", headers=login(client, "r01@a.ru")).json()
    assert director["delta_week"] is None
    hq = client.get("/api/overview/restaurants/R01", headers=login(client, "admin@a.ru")).json()
    assert "delta_week" in hq


# ------------------------------------------------------------------ code review of stage 6.1 (05.11.2026)


@pytest.mark.usefixtures("demo")
def test_r1_the_ais_basis_names_only_data_problems_the_director_sees(
    network: Network, owner_engine: Engine
) -> None:
    """The hypotheses' basis is kept and shown to whoever sees the finding: built by the HQ, it must not name
    an M7 finding of the restaurant that has no task yet."""
    from app.ai.finding_context import _data_problems

    with Session(owner_engine) as s:
        rid = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == "R10")
        ).scalar_one()
        m7 = s.execute(
            select(Finding.id, Finding.title).where(Finding.restaurant_id == rid, Finding.module == "M7")
        ).first()
        other = s.execute(
            select(Finding.id).where(Finding.restaurant_id == rid, Finding.module != "M7")
        ).scalar()
        assert m7 is not None and other is not None
        assert m7.title not in _data_problems(s, rid, other)  # no task on it yet
    hq_task(owner_engine, m7.id)
    with Session(owner_engine) as s:
        assert m7.title in _data_problems(s, rid, other)


@pytest.mark.usefixtures("demo")
def test_r2_a_digest_stored_before_shows_a_director_only_what_they_see(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """A director's digest built before ADR 0009 may hold an unassigned finding: left out on reading."""
    fid = _untasked(owner_engine, network)
    assert fid is not None
    director = login(client, "r01@a.ru")
    digest = client.post("/api/digests/rebuild", json={}, headers=director).json()
    with Session(owner_engine) as s, s.begin():
        d = s.get(Digest, UUID(digest["id"]))
        assert d is not None
        smuggled = {**d.input["problems"][0], "finding_id": str(fid), "title": "Без задачи"}
        d.input = {**d.input, "problems": [*d.input["problems"], smuggled]}
    shown = client.get("/api/digests/latest", headers=director).json()
    assert str(fid) not in str(shown) and "Без задачи" not in str(shown)
    assert str(fid) in str(
        client.get(
            f"/api/digests/latest?restaurant_id={digest['restaurant_id']}",
            headers=login(client, "admin@a.ru"),
        ).json()
    )


@pytest.mark.usefixtures("demo")
def test_r3_the_network_card_counts_what_the_badge_counts(client: TestClient) -> None:
    admin = login(client, "admin@a.ru")
    n = client.get("/api/overview/network?preset=week", headers=admin).json()
    badge = client.get("/api/overview/badges", headers=admin).json()["inbox"]
    assert n["findings_awaiting"] == len(client.get("/api/overview/awaiting", headers=admin).json())
    assert n["findings_awaiting"] + n["checks_waiting"] + n["overdue_tasks"] == badge


def test_r7_a_directors_digest_without_tasks_does_not_say_all_is_fine() -> None:
    from app.digests import texts

    empty: dict[str, object] = {
        "scope": "restaurant",
        "on_table": {"total": "0 ₽", "losses": "0 ₽", "potential": "0 ₽"},
        "problems": [],
        "opportunities": [],
        "risks": [],
        "processes": [],
        "improved": {"tasks_done": 0},
    }
    assert "Задач по находкам от управляющей компании пока нет" in texts.headline(empty)
    assert "Открытых проблем" in texts.headline({**empty, "scope": "network"})


# ------------------------------------------------------------- test engineer, end of stage 6.1 (05.11.2026)


def _add_director(owner_engine: Engine, network: Network, code: str) -> str:
    """One more director of the demo network (the `demo` fixture has only r01@a.ru)."""
    email = f"{code.lower()}@a.ru"
    with Session(owner_engine) as s, s.begin():
        rid = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == code)
        ).scalar_one()
        user = User(
            tenant_id=network.a.id, email=email, full_name=code, password_hash=hash_password(PASSWORD)
        )
        s.add(user)
        s.flush()
        s.add(
            RoleAssignment(
                tenant_id=network.a.id, user_id=user.id, role=Role.RESTAURANT_DIRECTOR, restaurant_id=rid
            )
        )
    return email


def _restaurant(owner_engine: Engine, network: Network, code: str) -> UUID:
    with Session(owner_engine) as s:
        rid: UUID = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == code)
        ).scalar_one()
        return rid


def _awaiting_ids(client: TestClient, admin: dict[str, str]) -> list[str]:
    return [f["id"] for f in client.get("/api/overview/awaiting", headers=admin).json()]


@pytest.mark.usefixtures("demo")
def test_an_unassigned_finding_is_not_found_by_a_director_on_any_endpoint_about_it(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """ADR 0009, p. 3: every endpoint that takes the finding's id answers a director as if there were no such
    finding (AI suggestions, «Откуда цифры», «Не согласен») or as to anyone who is not the HQ (the review's
    working notes, checks, the report to the head); after the HQ's task the director's ones open."""
    fid = _untasked(owner_engine, network)
    assert fid is not None
    director = login(client, "r01@a.ru")
    not_found = {
        "GET hypotheses": client.get(f"/api/findings/{fid}/hypotheses", headers=director),
        "POST hypotheses": client.post(f"/api/findings/{fid}/hypotheses", headers=director),
        "sources": client.get(f"/api/findings/{fid}/sources", headers=director),
        "disagree": client.post(
            f"/api/findings/{fid}/disagree", json={"reason": "wrong_data"}, headers=director
        ),
        "withdraw": client.delete(f"/api/findings/{fid}/disagree", headers=director),
    }
    assert {k: r.status_code for k, r in not_found.items()} == {k: 404 for k in not_found}
    assert all(str(fid) not in r.text for r in not_found.values())
    hq_only = {
        "verification": client.get(f"/api/findings/{fid}/verification", headers=director),
        "precheck": client.get(f"/api/findings/{fid}/precheck", headers=director),
        "checks": client.get("/api/checks", headers=director),
        "check draft": client.get(f"/api/checks/draft?finding_id={fid}", headers=director),
        "report": client.get("/api/reports/head", headers=director),
        "disagreements": client.get("/api/digests/disagreements", headers=director),
    }
    assert {k: r.status_code for k, r in hq_only.items()} == {k: 403 for k in hq_only}
    # Nothing was stored for the HQ from the 404s above.
    admin = login(client, "admin@a.ru")
    assert str(fid) not in client.get("/api/digests/disagreements", headers=admin).text

    hq_task(owner_engine, fid)
    assert client.get(f"/api/findings/{fid}/hypotheses", headers=director).status_code == 200
    assert client.get(f"/api/findings/{fid}/sources", headers=director).status_code == 200
    r = client.post(f"/api/findings/{fid}/disagree", json={"reason": "wrong_data"}, headers=director)
    assert r.status_code == 204  # «Не согласен» stays as feedback to the HQ (ADR 0009, p. 4)
    assert str(fid) in client.get("/api/digests/disagreements", headers=admin).text
    assert client.get(f"/api/findings/{fid}/verification", headers=director).status_code == 403


@pytest.mark.usefixtures("demo")
def test_the_chat_does_not_discuss_an_unassigned_finding_with_a_director(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """ADR 0009, p. 3 «ни в ответах чата»: a question asked from an unassigned finding's id is not tied to
    it — in `/chat` or `/chat/stream`; the model is not told about it, the answer does not link to it."""
    model = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(model)
    try:
        _chat_from_an_unassigned_finding(client, network, owner_engine, model)
    finally:
        app.dependency_overrides.pop(get_gateway, None)


def _chat_from_an_unassigned_finding(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    fid = _untasked(owner_engine, network)
    assert fid is not None
    director = login(client, "r01@a.ru")
    model.replies.append(text_reply("Ответ"))
    r = client.post("/api/chat", headers=director, json={"question": "Почему?", "finding_id": str(fid)})
    assert r.status_code == 200 and r.json()["source_finding_id"] is None
    assert str(fid) not in json.dumps(model.requests[-1].messages, ensure_ascii=False)
    model.replies.append(text_reply("Ответ"))
    with client.stream(
        "POST", "/api/chat/stream", headers=director, json={"question": "Почему?", "finding_id": str(fid)}
    ) as s:
        body = s.read().decode()
    assert "event: answer" in body and str(fid) not in body
    assert str(fid) not in json.dumps(model.requests[-1].messages, ensure_ascii=False)
    assert str(fid) not in client.get("/api/chat/threads", headers=director).text
    # The HQ's task: now the question from it goes to the model with it.
    hq_task(owner_engine, fid)
    model.replies.append(text_reply("Разберем."))
    r = client.post("/api/chat", headers=director, json={"question": "Почему?", "finding_id": str(fid)})
    assert r.json()["source_finding_id"] == str(fid)


@pytest.mark.usefixtures("demo")
def test_the_answer_by_rules_names_no_unassigned_finding(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """Without the model the chat answers by rules from the director's findings: only those with a task."""
    with Session(owner_engine) as s:
        rid = _restaurant(owner_engine, network, "R01")
        tasked = select(Task.finding_id).where(Task.restaurant_id == rid, Task.finding_id.is_not(None))
        hidden = set(
            s.execute(select(Finding.title).where(Finding.restaurant_id == rid, Finding.id.not_in(tasked)))
            .scalars()
            .all()
        ) - set(s.execute(select(Finding.title).where(Finding.id.in_(tasked))).scalars().all())
    assert hidden
    director = login(client, "r01@a.ru")
    for question in ("Где я теряю деньги?", "Что у меня с рисками?", "Какие у меня задачи?"):
        r = client.post("/api/chat", headers=director, json={"question": question})
        assert r.status_code == 200
        assert not [t for t in hidden if t in r.text], question


@pytest.mark.usefixtures("demo")
def test_a_network_finding_given_to_part_of_the_network_reaches_only_those_directors(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """ADR 0009, p. 2 and the 05.11 clarification: a network finding goes to the chosen restaurants — only
    their directors get the task; the others never meet it; the finding itself no director sees (p. 3)."""
    admin, director1 = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    director2 = login(client, _add_director(owner_engine, network, "R02"))
    net = next(
        f for f in client.get("/api/overview/awaiting", headers=admin).json() if not f["restaurant_id"]
    )
    due = str(TODAY + timedelta(days=7))
    r01 = _restaurant(owner_engine, network, "R01")
    made = client.post(
        "/api/tasks",
        json={
            "title": "Сверить цены",
            "due_on": due,
            "finding_id": net["id"],
            "restaurant_ids": [str(r01)],
            "checklist": ["Шаг 1", "Шаг 2"],
        },
        headers=admin,
    )
    assert made.status_code == 201, made.text
    assert [t["restaurant_id"] for t in made.json()] == [str(r01)]  # one task, not one per step
    assert made.json()[0]["checklist"] == ["Шаг 1", "Шаг 2"]
    assert net["id"] not in _awaiting_ids(client, admin)  # decided: leaves «Решить по находке»

    mine = [t for t in client.get("/api/tasks", headers=director1).json() if t["finding_id"] == net["id"]]
    assert len(mine) == 1 and mine[0]["finding_title"] is None and mine[0]["finding_effect_rub_month"] is None
    assert mine[0]["source"] == "Поставлено управляющей компанией"
    assert net["title"] not in client.get("/api/tasks", headers=director1).text
    for headers in (director1, director2):
        assert client.get(f"/api/findings/{net['id']}", headers=headers).status_code == 404
        assert net["id"] not in client.get("/api/findings", headers=headers).text
    assert net["id"] not in client.get("/api/tasks", headers=director2).text
    assert "Сверить цены" not in client.get("/api/tasks", headers=director2).text


@pytest.mark.usefixtures("demo")
def test_a_network_finding_without_chosen_restaurants_goes_to_every_restaurant(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    admin = login(client, "admin@a.ru")
    net = next(
        f for f in client.get("/api/overview/awaiting", headers=admin).json() if not f["restaurant_id"]
    )
    due = str(TODAY + timedelta(days=7))
    made = client.post(
        "/api/tasks", json={"title": "Всем", "due_on": due, "finding_id": net["id"]}, headers=admin
    )
    assert made.status_code == 201, made.text
    with Session(owner_engine) as s:
        every = {
            str(r)
            for r in s.execute(select(Restaurant.id).where(Restaurant.tenant_id == network.a.id)).scalars()
        }
    assert {t["restaurant_id"] for t in made.json()} == every and len(made.json()) == len(every)


@pytest.mark.usefixtures("demo")
def test_a_restaurants_finding_goes_to_its_restaurant_only_and_from_the_admin_only(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """ADR 0009 clarification: the analyst sees «Решить по находке», the HQ admin puts the task. A
    restaurant's finding cannot go to another restaurant (that director would meet someone else's finding)."""
    fid = _untasked(owner_engine, network)
    assert fid is not None
    admin, analyst = login(client, "admin@a.ru"), login(client, "analyst@a.ru")
    assert str(fid) in _awaiting_ids(client, analyst)
    due = str(TODAY + timedelta(days=3))
    body = {"title": "x", "due_on": due, "finding_id": str(fid)}
    assert client.post("/api/tasks", json=body, headers=analyst).status_code == 403
    r02 = _restaurant(owner_engine, network, "R02")
    wrong = client.post("/api/tasks", json={**body, "restaurant_ids": [str(r02)]}, headers=admin)
    assert wrong.status_code in (400, 422), wrong.text
    foreign = client.post("/api/tasks", json=body, headers=login(client, "admin@b.ru"))
    assert foreign.status_code == 404  # another network's finding: as if missing
    assert str(fid) in _awaiting_ids(client, admin)  # nothing was decided
    assert str(fid) not in client.get("/api/overview/awaiting", headers=login(client, "admin@b.ru")).text


@pytest.mark.usefixtures("demo")
def test_a_task_on_another_restaurants_finding_does_not_name_it_to_the_director(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """A rolled-out change: the task of R01 comes from a finding of R10 (`checks.rollout`). The director
    gets the task; the finding of another restaurant stays unseen — no title, no sum, no card."""
    other = _untasked(owner_engine, network, "R10")
    assert other is not None
    with Session(owner_engine) as s, s.begin():
        f = s.get(Finding, other)
        assert f is not None
        title = f.title
        s.add(
            Task(
                tenant_id=network.a.id,
                restaurant_id=_restaurant(owner_engine, network, "R01"),
                finding_id=other,
                assigned_by="hq",
                title="Тиражирование",
                checklist=[],
                checklist_done=[],
                created_on=TODAY,
                due_on=TODAY + timedelta(days=14),
            )
        )
    director = login(client, "r01@a.ru")
    tasks = client.get("/api/tasks", headers=director).json()
    rolled = [t for t in tasks if t["title"] == "Тиражирование"]
    assert len(rolled) == 1 and rolled[0]["finding_title"] is None
    assert rolled[0]["finding_effect_rub_month"] is None and title not in str(tasks)
    assert client.get(f"/api/findings/{other}", headers=director).status_code == 404
    assert str(other) not in client.get("/api/overview/restaurants/R01", headers=director).text


@pytest.mark.usefixtures("demo")
def test_a_rejected_check_returns_the_finding_to_awaiting(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """ADR 0009, p. 2: a finding with a proposed check leaves «Решить по находке» (it waits in «Проверки к
    запуску»); a rejected check is no decision — the finding comes back, the badge counts it once again."""
    admin, analyst = login(client, "admin@a.ru"), login(client, "analyst@a.ru")
    fid = _untasked(owner_engine, network, measured=True)  # a check needs a finding the measurement counts
    assert fid is not None
    badge = client.get("/api/overview/badges", headers=admin).json()["inbox"]
    draft = client.get(f"/api/checks/draft?finding_id={fid}", headers=analyst).json()
    check = client.post(
        "/api/checks",
        json={
            "finding_id": str(fid),
            "action": draft["actions"][0],
            "control_ids": [c["restaurant_id"] for c in draft["candidates"] if c["suggested"]],
            "weeks": draft["default_weeks"],
        },
        headers=analyst,
    )
    assert check.status_code == 201, check.text
    assert str(fid) not in _awaiting_ids(client, admin)
    # −1 finding awaiting, +1 check to launch: the badge is the same.
    assert client.get("/api/overview/badges", headers=admin).json()["inbox"] == badge
    assert client.get(f"/api/findings/{fid}", headers=login(client, "r01@a.ru")).status_code == 404

    assert client.post(f"/api/checks/{check.json()['id']}/reject", headers=admin).status_code == 200
    assert str(fid) in _awaiting_ids(client, admin)
    n = client.get("/api/overview/network?preset=week", headers=admin).json()
    assert n["findings_awaiting"] == len(_awaiting_ids(client, admin))
    assert client.get("/api/overview/badges", headers=admin).json()["inbox"] == badge
    assert client.get(f"/api/findings/{fid}", headers=login(client, "r01@a.ru")).status_code == 404


@pytest.mark.usefixtures("demo")
def test_without_the_review_a_finding_still_waits_for_the_hqs_task(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """The review switched off (docs/12 «Ручная проверка»): new findings skip «Проверка находок», not the HQ's
    decision — they wait in «Решить по находке», and a director meets only those with a task (ADR 0009)."""
    admin = login(client, "admin@a.ru")
    body = client.get("/api/settings/norms", headers=admin).json()
    assert (
        client.put("/api/settings/norms", headers=admin, json={**body, "review_findings": False}).status_code
        == 200
    )
    assert client.post("/api/analytics/run", headers=admin).status_code == 202
    r01 = _restaurant(owner_engine, network, "R01")
    awaiting = client.get("/api/overview/awaiting", headers=admin).json()
    own = {f["id"] for f in awaiting if f["restaurant_id"] == str(r01)}
    assert own
    with Session(owner_engine) as s:
        tasked = {
            str(f)
            for f in s.execute(select(Task.finding_id).where(Task.restaurant_id == r01)).scalars()
            if f is not None
        }
    seen = {f["id"] for f in client.get("/api/findings", headers=login(client, "r01@a.ru")).json()}
    assert seen <= tasked and not seen & own


@pytest.mark.usefixtures("demo")
def test_r2_a_digest_stored_before_does_not_name_an_unassigned_finding_in_its_headline(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """A digest built before ADR 0009, as the builder wrote it then: the unassigned finding is the top
    problem, so the headline by rules names it («Главное — «…»: … в месяц») and «На столе» counts it."""
    from app.digests import texts

    fid = _untasked(owner_engine, network)
    assert fid is not None
    director = login(client, "r01@a.ru")
    digest = client.post("/api/digests/rebuild", json={}, headers=director).json()
    with Session(owner_engine) as s, s.begin():
        d = s.get(Digest, UUID(digest["id"]))
        f = s.get(Finding, fid)
        assert d is not None and f is not None
        title = f.title
        smuggled = {**d.input["problems"][0], "finding_id": str(fid), "title": title}
        data = {**d.input, "problems": [smuggled, *d.input["problems"]]}
        d.input = data
        d.output = {**d.output, "headline": texts.headline(data)}  # what the builder wrote then
        assert title in d.output["headline"]
    shown = client.get("/api/digests/latest", headers=director).json()
    assert title not in shown["headline"]


@pytest.mark.usefixtures("demo")
def test_awaiting_puts_the_most_valuable_first_and_the_unpriced_last(client: TestClient) -> None:
    """docs/10 «Решить по находке»: дороже вверху — by «effect × confidence» as the week and the digest rank
    (high 1, medium 0.7, low 0.4 — `overview.CONFIDENCE_WEIGHT`), findings without a ruble estimate after
    them; each finding once."""
    from decimal import Decimal

    from app.overview.service import CONFIDENCE_WEIGHT

    awaiting = client.get("/api/overview/awaiting", headers=login(client, "admin@a.ru")).json()
    ids = [f["id"] for f in awaiting]
    assert len(ids) == len(set(ids))
    priced = [f for f in awaiting if f["effect_rub_month"]]
    unpriced = [f for f in awaiting if not f["effect_rub_month"]]
    assert awaiting == priced + unpriced
    value = [Decimal(f["effect_rub_month"]) * CONFIDENCE_WEIGHT[f["confidence"] or "medium"] for f in priced]
    assert value == sorted(value, reverse=True)


def test_the_findings_policy_a_task_opens_only_its_own_restaurants_finding(
    network: Network, owner_engine: Engine
) -> None:
    """Migration 0025 at the database level (TC-ISO): a director's session sees and may write a finding of
    their restaurant only with a task of that restaurant on it. A task of their restaurant on a network
    finding or on another restaurant's finding (a rolled-out change) opens neither; an unassigned finding
    cannot be changed blindly either (USING hides it; WITH CHECK keeps it visible)."""
    from sqlalchemy import text

    from app.core.db import RlsContext, apply_rls_context, get_sessionmaker

    a, a1, a2 = network.a.id, network.a.restaurants["A1"], network.a.restaurants["A2"]
    ids = {}
    with Session(owner_engine) as s, s.begin():
        for name, rid in (("own", a1), ("untasked", a1), ("net", None), ("other", a2)):
            f = Finding(
                tenant_id=a,
                restaurant_id=rid,
                kind="problem",
                process="production",
                title=name,
                actions=["Шаг"],
                found_on=TODAY,
                review_status="confirmed",
            )
            s.add(f)
            s.flush()
            ids[name] = f.id
        for name in ("own", "net", "other"):  # every task on A1
            s.add(
                Task(
                    tenant_id=a,
                    restaurant_id=a1,
                    finding_id=ids[name],
                    assigned_by="hq",
                    title=name,
                    checklist=[],
                    checklist_done=[],
                    created_on=TODAY,
                    due_on=TODAY + timedelta(days=7),
                )
            )
    session = get_sessionmaker()()
    try:
        apply_rls_context(session, RlsContext(a, network.a.users["director1@a.ru"], False, frozenset({a1})))
        assert session.execute(text("SELECT title FROM findings")).scalars().all() == ["own"]
        assert session.execute(text("SELECT count(*) FROM tasks")).scalar_one() == 3  # the tasks are theirs
        for name in ("untasked", "net", "other"):
            changed = session.execute(
                text("UPDATE findings SET status = 'resolved' WHERE id = :i"), {"i": ids[name]}
            )
            assert changed.rowcount == 0, name  # type: ignore[attr-defined]
    finally:
        session.rollback()
        session.close()
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM findings WHERE status = 'resolved'")).scalar_one() == 0
