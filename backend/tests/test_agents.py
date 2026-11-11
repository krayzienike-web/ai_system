"""Agents, stage 9 (ADR 0010): the code finds the reason and the list, the rules or the model write the text,
a person decides. Network A: A1 is due a stock count in 2 days and has tasks near and past their deadline."""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents import inventory, service, texts
from app.agents.models import AgentNote
from app.ai import agent_writer
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, text_reply
from app.catalog.models import Product
from app.core.period import get_today
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.main import app
from app.operations.models import InventoryCount, Receipt
from app.tasks.models import Task
from app.tenancy.context import system_context
from app.tenancy.models import AuditLog
from tests.conftest import Network, login

TODAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _batch(s: Session, tenant: UUID, restaurant: UUID, template: str, until: date | None = None) -> UUID:
    batch = ImportBatch(
        tenant_id=tenant,
        restaurant_id=restaurant,
        template=template,
        filename=f"{template}.csv",
        sha256=uuid4().hex * 2,
        raw=b"",
        status="published",
        period_from=until,
        period_to=until,
    )
    s.add(batch)
    s.flush()
    return batch.id


class World:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        a = network.a
        self.a, self.a1, self.a2, self.a3 = (
            a.id,
            a.restaurants["A1"],
            a.restaurants["A2"],
            a.restaurants["A3"],
        )
        with Session(owner_engine, expire_on_commit=False) as s, s.begin():
            p = {
                code: Product(tenant_id=a.id, code=code, name=f"Товар {code}", base_unit="kg")
                for code in ("P1", "P2", "P3", "P4")
            }
            s.add_all(p.values())
            s.flush()
            self.products = p
            receipts = _batch(s, a.id, self.a1, "receipts", date(2026, 9, 10))
            other = _batch(s, a.id, self.a2, "receipts", date(2026, 9, 10))
            for code, price in (("P1", "50"), ("P2", "100"), ("P3", "300")):
                s.add(_receipt(a.id, self.a1, receipts, p[code].id, Decimal(price)))
            s.add(_receipt(a.id, self.a2, other, p["P3"].id, Decimal(1000)))  # another restaurant's price
            counts = _batch(s, a.id, self.a1, "inventory_counts", date(2026, 9, 21))
            # A1 counts every 31 days: 21.08, 21.09 → the next on 22.10, in 2 days.
            for day, rows in (
                (date(2026, 8, 21), [("P1", 10, 10), ("P2", 10, 10), ("P3", 50, 50)]),
                (date(2026, 9, 21), [("P1", 10, 9), ("P2", 10, 8), ("P3", 50, 50)]),
            ):
                for code, book, actual in rows:
                    s.add(_count(a.id, self.a1, counts, day, p[code].id, book, actual))
            a2_counts = _batch(s, a.id, self.a2, "inventory_counts", date(2026, 9, 15))
            for day in (date(2026, 8, 16), date(2026, 9, 15)):  # 15.10 missed: the next on 14.11
                s.add(_count(a.id, self.a2, a2_counts, day, p["P1"].id, 5, 5))  # no price at A2: not listed
                s.add(_count(a.id, self.a2, a2_counts, day, p["P3"].id, 5, 5))
            seen = _finding(a.id, self.a1, "M1:A1:P1", "Перерасход товара P1")
            unseen = _finding(a.id, self.a1, "M1:A1:P4", "Перерасход товара P4 без задачи")
            s.add_all([seen, unseen])
            s.flush()
            self.seen_finding = seen.id
            self.finding_task = _task(a.id, self.a1, "Задача по находке", date(2026, 10, 30), finding=seen.id)
            self.due = _task(a.id, self.a1, "Пересчитать сыры", date(2026, 10, 21), steps=["Шаг 1", "Шаг 2"])
            self.due.checklist_done = [True, False]
            self.stuck = _task(a.id, self.a1, "Проверить выход филе", date(2026, 10, 17))
            self.late_two = _task(a.id, self.a1, "Две недели", date(2026, 10, 18))
            self.started = _task(a.id, self.a2, "Начатая", date(2026, 10, 10), status="in_progress")
            s.add_all([self.finding_task, self.due, self.stuck, self.late_two, self.started])
            # A2 and A3 are up to date with every export but one: A3 has no write-offs this week.
            for rid in (self.a1, self.a2, self.a3):
                for template in ("sales", "receipts", "write_offs"):
                    if rid == self.a3 and template == "write_offs":
                        continue
                    _batch(s, a.id, rid, template, date(2026, 10, 18))
            _batch(s, a.id, self.a3, "inventory_counts", date(2026, 9, 1))


def _receipt(tenant: UUID, restaurant: UUID, batch: UUID, product: UUID, price: Decimal) -> Receipt:
    return Receipt(
        tenant_id=tenant,
        restaurant_id=restaurant,
        import_batch_id=batch,
        day=date(2026, 9, 10),
        product_id=product,
        qty=Decimal(10),
        amount=price * 10,
    )


def _count(
    tenant: UUID, restaurant: UUID, batch: UUID, day: date, product: UUID, book: int, actual: int
) -> InventoryCount:
    return InventoryCount(
        tenant_id=tenant,
        restaurant_id=restaurant,
        import_batch_id=batch,
        day=day,
        product_id=product,
        book_qty=Decimal(book),
        actual_qty=Decimal(actual),
    )


def _finding(tenant: UUID, restaurant: UUID, key: str, title: str) -> Finding:
    return Finding(
        tenant_id=tenant,
        restaurant_id=restaurant,
        kind="problem",
        process="production",
        title=title,
        effect_rub_month=Decimal(1000),
        found_on=TODAY,
        key=key,
        module="M1",
        review_status="confirmed",
    )


def _task(
    tenant: UUID,
    restaurant: UUID,
    title: str,
    due: date,
    *,
    steps: list[str] | None = None,
    finding: UUID | None = None,
    status: str = "assigned",
) -> Task:
    steps = steps or []
    return Task(
        tenant_id=tenant,
        restaurant_id=restaurant,
        finding_id=finding,
        title=title,
        checklist=steps,
        checklist_done=[False] * len(steps),
        assigned_by="hq",
        created_on=date(2026, 10, 1),
        due_on=due,
        status=status,
    )


@pytest.fixture
def world(network: Network, owner_engine: Engine) -> World:
    return World(network, owner_engine)


def _notes(owner_engine: Engine, agent: str | None = None) -> list[AgentNote]:
    """Network A's notes (network B, with no data at all, has its own data checks)."""
    with Session(owner_engine) as s:
        q = select(AgentNote).where(AgentNote.key.not_like("%:B1:%")).order_by(AgentNote.key)
        if agent:
            q = q.where(AgentNote.agent == agent)
        return list(s.execute(q).scalars())


def _by(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    response = client.get("/api/agents/notes", headers=headers)
    assert response.status_code == 200, response.text
    return {n["agent"] + ":" + n["restaurant_code"]: n for n in response.json()}


# ------------------------------------------------------------------ № 1: before a stock count


def test_the_next_count_is_the_usual_interval_after_the_last() -> None:
    """TC-AG-01: the median of the gaps; a missed count moves a cycle on; one count gives no interval."""
    s = inventory.schedule([date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1), date(2026, 9, 1)], TODAY)
    assert s is not None and s.typical_days == 30 and s.expected == date(2026, 10, 31)
    missed = inventory.schedule([date(2026, 8, 1), date(2026, 9, 1)], TODAY)  # 02.10 did not happen
    assert missed is not None and missed.typical_days == 31 and missed.expected == date(2026, 11, 2)
    assert inventory.schedule([date(2026, 8, 1)], TODAY) is None
    assert inventory._finding_products("M1:R01:P01:under", {"P01"}) == ["P01"]
    assert inventory._finding_products("M4:R11:P02-P03", {"P02", "P03"}) == ["P02", "P03"]
    assert inventory._finding_products("M1:net:P01", {"P01"}) == []
    assert inventory._finding_products("M4:R12:paper", {"P01"}) == []


def test_two_days_before_the_count_the_director_gets_what_to_count_carefully(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-02: the finding the director sees, the shortage in rubles, the valuable stock — by the restaurant
    's own prices; a finding without the HQ's task stays out (ADR 0009); A2's next count is weeks away."""
    assert service.run_all(TODAY) >= 1
    (note,) = _notes(owner_engine, "inventory_prep")
    assert (
        note.restaurant_id == world.a1 and note.audience == "director" and note.for_date == date(2026, 10, 22)
    )
    products = {p["code"]: p for p in note.facts["products"]}
    assert products["P1"]["reason"] == "finding" and products["P1"]["finding"] == "Перерасход товара P1"
    assert products["P2"] == {**products["P2"], "reason": "shortage", "diff_rub": "200"}
    assert products["P3"] == {
        **products["P3"],
        "reason": "value",
        "stock_rub": "15000",
    }  # A1's 300 ₽, not A2's
    assert "P4" not in products
    assert note.items[0] == "Товар P1 — по нему открыта находка «Перерасход товара P1»"
    assert "Товар P2 — на пересчете 21.09 не хватило на 200\u00a0₽" in note.items
    assert "Товар P3 — дорогой остаток: 15\u00a0000\u00a0₽ на 21.09" in note.items
    assert note.title == "Инвентаризация 22.10: что пересчитать внимательно" and note.source == "rules"
    # Three days before: nothing yet.
    with Session(owner_engine) as s, s.begin():
        system_context(s, world.a)
        assert inventory.drafts(s, list(_restaurants(s)), TODAY - timedelta(days=1)) == []


def _restaurants(s: Session) -> Any:
    from app.tenancy.models import Restaurant

    return s.execute(select(Restaurant).order_by(Restaurant.code)).scalars()


def test_the_director_takes_the_list_into_work_as_a_task(
    world: World, network: Network, client: TestClient, owner_engine: Engine
) -> None:
    """TC-AG-03: «Создать задачу» — a task of the director's with the list, due on the count's day; once."""
    service.run_all(TODAY)
    director = login(client, "director1@a.ru")
    note = _by(client, director)["inventory_prep:A1"]
    assert note["action"] == "create_task" and note["action_due_on"] == "2026-10-22"
    answer = client.post(f"/api/agents/notes/{note['id']}/accept", headers=director)
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "accepted"
    with Session(owner_engine) as s:
        task = s.get(Task, UUID(answer.json()["result_task_id"]))
        assert task is not None and task.assigned_by == "director" and task.due_on == date(2026, 10, 22)
        assert task.title == "Подготовка к инвентаризации 22.10"
        assert task.checklist[0] == "Пересчитать: Товар P1 — по нему открыта находка «Перерасход товара P1»"
        assert s.execute(select(func.count()).where(AuditLog.action == "agent_note.accepted")).scalar() == 1
    assert client.post(f"/api/agents/notes/{note['id']}/accept", headers=director).status_code == 409
    # Decided: gone from the list, and the next run does not bring it back.
    service.run_all(TODAY)
    assert "inventory_prep:A1" not in _by(client, director)
    assert [n.status for n in _notes(owner_engine, "inventory_prep")] == ["accepted"]


def test_a_list_can_be_asked_for_a_chosen_day(world: World, client: TestClient, owner_engine: Engine) -> None:
    """TC-AG-04: the director of a restaurant whose count is not where the interval puts it asks for a list;
    only for their own restaurant, from today and up to 14 days ahead; it stays until its day."""
    director2 = login(client, "director2@a.ru")
    body = {"restaurant_id": str(world.a2), "count_on": "2026-10-23"}
    answer = client.post("/api/agents/inventory-prep", json=body, headers=director2)
    assert answer.status_code == 200, answer.text
    assert answer.json()["for_date"] == "2026-10-23" and answer.json()["items"]
    assert (
        client.post("/api/agents/inventory-prep", json=body, headers=director2).json()["id"]
        == answer.json()["id"]
    )
    other = {"restaurant_id": str(world.a1), "count_on": "2026-10-23"}
    assert client.post("/api/agents/inventory-prep", json=other, headers=director2).status_code in (403, 404)
    late = {**body, "count_on": "2026-11-20"}
    assert client.post("/api/agents/inventory-prep", json=late, headers=director2).status_code == 422
    past = {**body, "count_on": "2026-10-19"}
    assert client.post("/api/agents/inventory-prep", json=past, headers=director2).status_code == 422
    never = {"restaurant_id": str(world.a3), "count_on": "2026-10-23"}  # A3 has never counted
    admin = login(client, "admin@a.ru")
    assert client.post("/api/agents/inventory-prep", json=never, headers=admin).status_code == 422
    analyst = login(client, "analyst@a.ru")
    assert client.post("/api/agents/inventory-prep", json=body, headers=analyst).status_code == 403
    service.run_all(TODAY)  # not where the interval puts it, but asked for: it stays
    assert "inventory_prep:A2" in _by(client, director2)
    service.run_all(date(2026, 10, 24))  # its day has passed
    assert [n.status for n in _notes(owner_engine, "inventory_prep") if n.restaurant_id == world.a2] == [
        "expired"
    ]
    with Session(owner_engine) as s, s.begin():  # counted, but nothing priced and no findings: nothing to say
        s.query(InventoryCount).filter(InventoryCount.product_id == world.products["P3"].id).delete()
    a2_again = {**body, "count_on": "2026-10-24"}
    refused = client.post("/api/agents/inventory-prep", json=a2_again, headers=admin)
    assert refused.status_code == 422 and "Подсказать нечего" in refused.json()["detail"]


def test_an_asked_list_stays_true_and_can_be_asked_again(
    world: World, client: TestClient, owner_engine: Engine
) -> None:
    """TC-AG-13 (backend review of stage 9, pp. 2–3): each morning until its day the list is computed again
    («через 3 дня» becomes «через 1 день»); asked again after it was put away — new again; once it became a
    task — refused."""
    director2 = login(client, "director2@a.ru")
    body = {"restaurant_id": str(world.a2), "count_on": "2026-10-23"}
    first = client.post("/api/agents/inventory-prep", json=body, headers=director2).json()
    assert first["text"].startswith("Пересчет через 3 дня, 23.10")
    service.run_all(date(2026, 10, 22))
    (note,) = [n for n in _notes(owner_engine, "inventory_prep") if n.restaurant_id == world.a2]
    assert note.status == "new" and note.text.startswith("Пересчет завтра, 23.10")
    assert client.post(f"/api/agents/notes/{first['id']}/dismiss", headers=director2).status_code == 200
    again = client.post("/api/agents/inventory-prep", json=body, headers=director2)
    assert again.status_code == 200 and again.json()["id"] == first["id"] and again.json()["status"] == "new"
    assert client.post(f"/api/agents/notes/{first['id']}/accept", headers=director2).status_code == 200
    taken = client.post("/api/agents/inventory-prep", json=body, headers=director2)
    assert taken.status_code == 409 and "уже стал задачей" in taken.json()["detail"]


def test_two_writers_of_one_reason_meet_on_the_row(world: World, owner_engine: Engine) -> None:
    """TC-AG-14 (p. 4): a double click — two asks at once — gives one note, no unique-key error."""
    import threading

    from app.core.db import get_sessionmaker
    from app.tenancy.context import load_access_context
    from app.tenancy.models import User

    with Session(owner_engine) as o:
        director = o.execute(select(User.id).where(User.email == "director2@a.ru")).scalar_one()
    barrier, ids, errors = threading.Barrier(2), [], []

    def ask() -> None:
        try:
            with get_sessionmaker()() as s:
                ctx = load_access_context(s, director, world.a)
                assert ctx is not None
                barrier.wait()
                ids.append(service.ask_inventory(s, ctx, world.a2, date(2026, 10, 23), today=TODAY).id)
                s.commit()
        except Exception as e:  # pragma: no cover - the failure this test is about
            errors.append(e)

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(set(ids)) == 1


def test_a_run_does_not_undo_a_decision_made_meanwhile(world: World, owner_engine: Engine) -> None:
    """TC-AG-15 (p. 5): the expiry touches only notes still new — an answer given during the run stays."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "task_due")
    with Session(owner_engine) as s, s.begin():
        n = s.get(AgentNote, note.id)
        assert n is not None
        n.status = "dismissed"
        t = s.get(Task, world.due.id)
        assert t is not None
        t.status, t.done_on = "done", TODAY  # the reason is gone too
    service.run_all(TODAY)
    assert [n.status for n in _notes(owner_engine, "task_due")] == ["dismissed"]


def test_answers_stay_within_the_restaurant(world: World, client: TestClient, owner_engine: Engine) -> None:
    """TC-AG-16 (p. 7): another director of the network does not answer A1's notes (404); A1's director
    answers a list the HQ admin asked for A1; a deadline proposal gone stale is refused."""
    service.run_all(TODAY)
    director1, director2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    prep = _by(client, director1)["inventory_prep:A1"]
    for answer in ("accept", "dismiss"):
        assert client.post(f"/api/agents/notes/{prep['id']}/{answer}", headers=director2).status_code == 404
    admin = login(client, "admin@a.ru")
    asked = client.post(
        "/api/agents/inventory-prep",
        json={"restaurant_id": str(world.a1), "count_on": "2026-10-25"},
        headers=admin,
    ).json()
    assert client.post(f"/api/agents/notes/{asked['id']}/accept", headers=director1).status_code == 200
    stuck = _by(client, admin)["task_stuck:A1"]
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 28)  # the proposal said 27.10
    assert client.post(f"/api/agents/notes/{stuck['id']}/accept", headers=admin).status_code == 422


# ------------------------------------------------------------------ № 7: deadlines


def test_the_director_is_reminded_of_a_deadline_with_what_is_left(world: World, owner_engine: Engine) -> None:
    """TC-AG-05: due tomorrow, one step of two left; done — the note expires."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "task_due")
    assert note.task_id == world.due.id and note.audience == "director"
    assert note.title == "Срок задачи завтра: Пересчитать сыры"
    assert note.text == "Задача «Пересчитать сыры» — срок 21.10, осталось 1 шаг из 2. Задача еще не начата."
    assert note.items == ["Шаг 2"]
    with Session(owner_engine) as s, s.begin():
        t = s.get(Task, world.due.id)
        assert t is not None
        t.status, t.done_on = "done", TODAY
    service.run_all(TODAY)
    assert [n.status for n in _notes(owner_engine, "task_due")] == ["expired"]


def test_a_stuck_task_goes_to_the_hq_and_only_the_admin_moves_its_deadline(
    world: World, client: TestClient, owner_engine: Engine
) -> None:
    """TC-AG-06: 3 days late and not started → to the HQ with «перенести на 27.10»; 2 days late or started —
    nothing. The director does not see it, the analyst may not answer, the admin moves the deadline."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "task_stuck")
    assert note.task_id == world.stuck.id and note.audience == "hq"
    assert note.proposal == {"action": "move_due", "due_on": "2026-10-27"}
    director = login(client, "director1@a.ru")
    assert "task_stuck:A1" not in _by(client, director)
    assert client.post(f"/api/agents/notes/{note.id}/accept", headers=director).status_code == 404
    assert client.post(f"/api/agents/notes/{note.id}/dismiss", headers=director).status_code == 404
    analyst = login(client, "analyst@a.ru")
    assert "task_stuck:A1" in _by(client, analyst)
    assert client.post(f"/api/agents/notes/{note.id}/accept", headers=analyst).status_code == 403
    admin = login(client, "admin@a.ru")
    assert client.post(f"/api/agents/notes/{note.id}/accept", headers=admin).status_code == 200
    with Session(owner_engine) as s:
        t = s.get(Task, world.stuck.id)
        assert t is not None and t.due_on == date(2026, 10, 27)
        moved = s.execute(select(AuditLog).where(AuditLog.action == "task.move_due")).scalar_one()
        assert moved.payload == {"from": "2026-10-17", "to": "2026-10-27"}
    service.run_all(TODAY)  # the deadline moved: no new note about the old one
    assert [n.status for n in _notes(owner_engine, "task_stuck")] == ["accepted"]


def test_moving_a_deadline_keeps_the_task_rules(world: World, owner_engine: Engine) -> None:
    """TC-AG-07: only the HQ admin moves a deadline; not into the past, past 90 days or on a done task."""
    from app.core.db import get_sessionmaker
    from app.core.errors import ForbiddenError, InvalidError
    from app.tasks.service import move_due
    from app.tenancy.context import load_access_context
    from app.tenancy.models import User

    with Session(owner_engine) as o:
        ids = dict(o.execute(select(User.email, User.id).where(User.tenant_id == world.a)).tuples().all())
    with get_sessionmaker()() as s:
        director = load_access_context(s, ids["director1@a.ru"], world.a)
        assert director is not None
        with pytest.raises(ForbiddenError):
            move_due(s, director, world.stuck.id, TODAY, today=TODAY)
        s.rollback()
        admin = load_access_context(s, ids["admin@a.ru"], world.a)
        assert admin is not None
        for bad in (TODAY - timedelta(days=1), TODAY + timedelta(days=91)):
            with pytest.raises(InvalidError):
                move_due(s, admin, world.stuck.id, bad, today=TODAY)
        t = s.get(Task, world.started.id)
        assert t is not None
        t.status, t.done_on = "done", TODAY
        s.flush()
        with pytest.raises(InvalidError, match="уже выполнена"):
            move_due(s, admin, world.started.id, TODAY, today=TODAY)
        s.rollback()


# ------------------------------------------------------------------ № 9: the morning data check


def test_the_morning_check_names_the_missing_exports_and_expires_when_they_come(
    world: World, owner_engine: Engine, client: TestClient
) -> None:
    """TC-AG-08: A3 has no write-offs this week → a note to its director; A1 and A2 are complete. The file
    arrives → the note expires on the next run. One a day, the same on a second run."""
    service.run_all(TODAY)
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "data_check")
    assert note.restaurant_id == world.a3 and note.key == "data_check:A3:2026-10-20"
    assert note.items == ["Списания — ни одной выгрузки"]
    director3 = login(client, "director3@a.ru")
    assert list(_by(client, director3)) == ["data_check:A3"]
    assert _by(client, login(client, "director2@a.ru")) == {}  # not another restaurant's notes
    with Session(owner_engine) as s, s.begin():
        _batch(s, world.a, world.a3, "write_offs", date(2026, 10, 18))
    service.run_all(TODAY)
    assert [n.status for n in _notes(owner_engine, "data_check")] == ["expired"]


def test_a_note_without_a_proposal_is_only_put_away(world: World, client: TestClient) -> None:
    """TC-AG-09: a reminder proposes nothing: «Создать задачу» is refused, «Скрыть» works for its director."""
    service.run_all(TODAY)
    director = login(client, "director1@a.ru")
    note = _by(client, director)["task_due:A1"]
    assert note["action"] is None
    assert client.post(f"/api/agents/notes/{note['id']}/accept", headers=director).status_code == 422
    assert (
        client.post(f"/api/agents/notes/{note['id']}/dismiss", headers=director).json()["status"]
        == "dismissed"
    )
    assert "task_due:A1" not in _by(client, director)
    hq = _by(client, login(client, "admin@a.ru"))
    assert {"inventory_prep:A1", "task_stuck:A1", "data_check:A3"} <= set(hq)


# ------------------------------------------------------------------ the model's text


def _model(text: str) -> Any:
    def reply(request: ModelRequest) -> Reply:
        return text_reply(json.dumps({"text": text}, ensure_ascii=False))

    return reply


def test_the_models_text_quotes_only_the_facts(world: World, owner_engine: Engine) -> None:
    """TC-AG-10: a text with the facts' numbers is the model's; a figure not in the facts — one request to
    correct, then the rules' text. The list stays the code's."""
    fake = FakeModel()
    fake.replies += [_model("Пересчет 22.10: начните с товара P1 — по нему открыта находка.")] * 20
    service.run_all(TODAY, lambda ctx: agent_writer.writer(Gateway(fake), ctx))
    (note,) = _notes(owner_engine, "inventory_prep")
    assert note.source == "model" and note.prompt_version == 1
    assert note.text.startswith("Пересчет 22.10") and note.items[0].startswith("Товар P1")
    with Session(owner_engine) as s, s.begin():
        s.query(AgentNote).delete()
    wrong = FakeModel()
    wrong.replies += [_model("Пересчитайте 7 позиций, недостача 9 999 ₽.")] * 40
    service.run_all(TODAY, lambda ctx: agent_writer.writer(Gateway(wrong), ctx))
    (note,) = _notes(owner_engine, "inventory_prep")
    assert note.source == "rules" and note.text == texts.inventory(note.facts)[1]


def test_a_failing_writer_never_costs_the_note(world: World, owner_engine: Engine) -> None:
    def broken(agent: str, facts: dict[str, Any], rules_text: str) -> tuple[str, int] | None:
        raise RuntimeError("down")

    service.run_all(TODAY, lambda ctx: broken)
    assert all(n.source == "rules" for n in _notes(owner_engine))
    assert _notes(owner_engine, "inventory_prep")


def test_one_networks_failure_does_not_stop_the_others(
    world: World, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-AG-11: an agent failing on one network: the others still get their notes."""
    real = service.run_network
    calls: list[UUID] = []

    def flaky(session: Session, tenant_id: UUID, today: date, write: Any = None) -> int:
        calls.append(tenant_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(session, tenant_id, today, write)

    monkeypatch.setattr(service, "run_network", flaky)
    service.run_all(TODAY)
    assert len(calls) == 2


def test_the_rules_say_days_and_steps_in_russian() -> None:
    assert (
        texts._days(0) == "сегодня" and texts._days(2) == "через 2 дня" and texts._days(5) == "через 5 дней"
    )
    assert texts._days(21) == "через 21 день" and texts._days(11) == "через 11 дней"
    assert texts._steps(1) == "1 шаг" and texts._steps(3) == "3 шага" and texts._steps(12) == "12 шагов"
    assert texts._positions(1) == "1 позиция" and texts._positions(3) == "3 позиции"
    assert texts._positions(5) == "5 позиций" and texts._positions(21) == "21 позиция"
    done = {"task": "Т", "due_on": "2026-10-21", "days_left": 1, "status": "in_progress", "steps_total": 1}
    assert texts.task_due({**done, "steps_left": []})[1] == "Задача «Т» — срок 21.10, все шаги отмечены."
    bare = {**done, "steps_total": 0, "steps_left": []}
    assert "Отметьте ее выполненной" in texts.task_due(bare)[1]
    missing = {"template": "sales", "status": "stale", "last_date": "2026-10-11"}
    assert texts._missing_line(missing) == "Продажи — последние данные за 11.10"
