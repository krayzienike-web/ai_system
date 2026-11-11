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
from app.imports.templates import TEMPLATES
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
    with Session(owner_engine) as s:  # the failed network has nothing, the other one its notes
        tenants = set(s.execute(select(AgentNote.tenant_id)).scalars())
    assert tenants == {calls[1]}


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


# ------------------------------------------------------------------ end-of-stage pass of the test engineer


def test_the_rules_texts_at_their_edges() -> None:
    """TC-AG-17: Russian plurals at 11–14, 21, 22, 101, 111; «сегодня» on the count's day; the stuck-task and
    data-check texts say exactly the facts' days and dates."""
    assert (
        texts._days(1) == "завтра"
        and texts._days(12) == "через 12 дней"
        and texts._days(14) == "через 14 дней"
    )
    assert texts._days(22) == "через 22 дня" and texts._days(101) == "через 101 день"
    assert texts._days(111) == "через 111 дней"
    assert texts._positions(11) == "11 позиций" and texts._positions(12) == "12 позиций"
    assert texts._positions(22) == "22 позиции" and texts._positions(111) == "111 позиций"
    assert texts._steps(11) == "11 шагов" and texts._steps(21) == "21 шаг" and texts._steps(24) == "24 шага"
    facts = {
        "count_on": "2026-10-22",
        "days_left": 0,
        "last_count": "2026-09-21",
        "products": [
            {"code": "P1", "name": "Сыр", "reason": "finding", "finding": "Перерасход сыра"},
            {"code": "P2", "name": "Филе", "reason": "shortage", "diff_rub": "1234567"},
            {"code": "P3", "name": "Икра", "reason": "value", "stock_rub": "999"},
        ],
    }
    title, text, items = texts.inventory(facts)
    assert title == "Инвентаризация 22.10: что пересчитать внимательно"
    assert text == (
        "Пересчет сегодня, 22.10. По прошлому пересчету 21.09 и открытым находкам в списке 3 позиции: "
        "их стоит пересчитать первыми и дважды."
    )
    assert items == [
        "Сыр — по нему открыта находка «Перерасход сыра»",
        "Филе — на пересчете 21.09 не хватило на 1 234 567 ₽",
        "Икра — дорогой остаток: 999 ₽ на 21.09",
    ]
    stuck = {"task": "Т", "due_on": "2026-10-17", "days_late": 3, "move_to": "2026-10-27"}
    assert texts.task_stuck(stuck) == (
        "Задача просрочена и не начата",
        "«Т» — срок был 17.10, просрочена на 3 дн., к ней еще не приступили. "
        "Можно перенести срок на 27.10 или обсудить задачу с директором.",
        [],
    )
    check = {
        "missing": [
            {"template": "sales", "status": "missing", "last_date": None},
            {"template": "write_offs", "status": "stale", "last_date": "2026-10-11"},
        ]
    }
    _, _, lines = texts.data_check(check)
    assert lines == [
        f"{TEMPLATES['sales'].title} — ни одной выгрузки",
        f"{TEMPLATES['write_offs'].title} — последние данные за 11.10",
    ]
    assert texts.by_rules("task_stuck", stuck) == texts.task_stuck(stuck)


def test_the_count_day_itself_gets_the_list_and_the_day_after_does_not(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-18: «за 0–2 дня»: on 22.10, the day of the count, the list says «сегодня»; on 23.10 the count did
    not happen — the next is a cycle on (22.11), no list."""
    with Session(owner_engine) as s, s.begin():
        system_context(s, world.a)
        (today,) = inventory.drafts(s, list(_restaurants(s)), date(2026, 10, 22))
        assert today.for_date == date(2026, 10, 22) and today.facts["days_left"] == 0
        assert texts.inventory(today.facts)[1].startswith("Пересчет сегодня, 22.10")
        assert inventory.drafts(s, list(_restaurants(s)), date(2026, 10, 23)) == []


def test_the_list_holds_at_most_twelve_products_seen_by_the_director(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-19: 13 checked findings with a task, plus one bigger finding still waiting for the review: the
    list has 12 products — the 12 largest checked findings by effect; the pending one is not there (the
    director does not see it, ADR 0009), and the shortage/stock lines no longer fit."""
    with Session(owner_engine) as s, s.begin():
        for i in range(14):
            code = f"Q{i:02d}"
            prod = Product(tenant_id=world.a, code=code, name=f"Товар {code}", base_unit="kg")
            s.add(prod)
            f = _finding(world.a, world.a1, f"M1:A1:{code}", f"Находка {code}")
            # Q00 is the biggest (9999 ₽) but not checked; Q01…Q13: 4990, 4980, … 4870 ₽ — above P1's 1000.
            f.effect_rub_month = Decimal(9999) if i == 0 else Decimal(5000 - 10 * i)
            if i == 0:
                f.review_status = "pending"
            s.add(f)
            s.flush()
            s.add(_task(world.a, world.a1, f"Задача {code}", date(2026, 11, 30), finding=f.id))
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "inventory_prep")
    codes = [p["code"] for p in note.facts["products"]]
    assert inventory.MAX_ITEMS == 12
    assert codes == [f"Q{i:02d}" for i in range(1, 13)]  # Q13 (4870 ₽), P1, P2, P3 are cut by the cap
    assert {p["reason"] for p in note.facts["products"]} == {"finding"}
    assert len(note.items) == 12 and "в списке 12 позиций" in note.text


def test_the_morning_check_names_a_stale_export_with_its_last_day(world: World, owner_engine: Engine) -> None:
    """TC-AG-20: today 20.10 (Tue), the last full week is 12.10–18.10. A2's write-offs up to 11.10 are stale:
    «Списания — последние данные за 11.10»; up to 12.10 they are fresh and the note expires. A3 with no stock
    count ever gets that line too. The next day — a note of its own, yesterday's expires."""

    def a2_write_offs_until(day: date) -> None:
        with Session(owner_engine) as s, s.begin():
            for b in s.execute(
                select(ImportBatch).where(
                    ImportBatch.restaurant_id == world.a2, ImportBatch.template == "write_offs"
                )
            ).scalars():
                b.period_from = b.period_to = day

    a2_write_offs_until(date(2026, 10, 11))
    with Session(owner_engine) as s, s.begin():
        s.query(ImportBatch).filter(
            ImportBatch.restaurant_id == world.a3, ImportBatch.template == "inventory_counts"
        ).delete()
    service.run_all(TODAY)
    notes = {n.restaurant_id: n for n in _notes(owner_engine, "data_check")}
    assert notes[world.a2].facts["missing"] == [
        {"template": "write_offs", "status": "stale", "last_date": "2026-10-11"}
    ]
    assert notes[world.a2].items == [f"{TEMPLATES['write_offs'].title} — последние данные за 11.10"]
    assert notes[world.a3].items == [
        f"{TEMPLATES['write_offs'].title} — ни одной выгрузки",
        f"{TEMPLATES['inventory_counts'].title} — ни одной выгрузки",
    ]
    assert world.a1 not in notes
    a2_write_offs_until(date(2026, 10, 12))  # the first day of the last full week: fresh
    service.run_all(TODAY)
    status = {(n.restaurant_id, n.for_date): n.status for n in _notes(owner_engine, "data_check")}
    assert status == {(world.a2, TODAY): "expired", (world.a3, TODAY): "new"}
    service.run_all(TODAY + timedelta(days=1))
    status = {(n.restaurant_id, n.for_date): n.status for n in _notes(owner_engine, "data_check")}
    assert status == {
        (world.a2, TODAY): "expired",
        (world.a3, TODAY): "expired",
        (world.a3, TODAY + timedelta(days=1)): "new",
    }


def test_the_api_names_what_create_task_does(world: World, client: TestClient) -> None:
    """TC-AG-21: NoteOut — the list gives the task's title and day, the stuck task — the new deadline, a
    reminder — nothing to do; the restaurant's code and name, the source and the status."""
    service.run_all(TODAY)
    director = _by(client, login(client, "director1@a.ru"))
    prep, due = director["inventory_prep:A1"], director["task_due:A1"]
    assert {k: prep[k] for k in ("action", "action_due_on", "action_title", "task_id", "for_date")} == {
        "action": "create_task",
        "action_due_on": "2026-10-22",
        "action_title": "Подготовка к инвентаризации 22.10",
        "task_id": None,
        "for_date": "2026-10-22",
    }
    assert prep["restaurant_id"] == str(world.a1) and prep["restaurant_code"] == "A1"
    assert prep["restaurant_name"].endswith("A1") and prep["audience"] == "director"
    assert (prep["source"], prep["status"], prep["result_task_id"]) == ("rules", "new", None)
    assert (due["action"], due["action_due_on"], due["action_title"]) == (None, None, None)
    assert due["task_id"] == str(world.due.id) and due["for_date"] == "2026-10-21"
    stuck = _by(client, login(client, "admin@a.ru"))["task_stuck:A1"]
    assert (stuck["action"], stuck["action_due_on"], stuck["action_title"]) == (
        "move_due",
        "2026-10-27",
        None,
    )
    assert stuck["audience"] == "hq" and stuck["task_id"] == str(world.stuck.id)


def test_the_hq_filters_the_notes_by_restaurant(world: World, client: TestClient) -> None:
    """TC-AG-22: `?restaurant=` — the HQ gets one restaurant's notes; a director asking for another restaurant
    gets nothing (RLS), for their own — their notes."""
    service.run_all(TODAY)

    def codes(headers: dict[str, str], restaurant: UUID) -> list[str]:
        response = client.get("/api/agents/notes", params={"restaurant": str(restaurant)}, headers=headers)
        assert response.status_code == 200, response.text
        return sorted(n["agent"] + ":" + n["restaurant_code"] for n in response.json())

    admin, analyst = login(client, "admin@a.ru"), login(client, "analyst@a.ru")
    assert codes(admin, world.a3) == ["data_check:A3"]
    assert codes(analyst, world.a1) == ["inventory_prep:A1", "task_due:A1", "task_stuck:A1"]
    assert codes(admin, world.a2) == []
    director1 = login(client, "director1@a.ru")
    assert codes(director1, world.a3) == []
    assert codes(director1, world.a1) == ["inventory_prep:A1", "task_due:A1"]


def test_the_writer_asks_once_to_correct_a_figure_then_keeps_the_rules(network: Network) -> None:
    """TC-AG-23: `agent_writer` — a figure not in the facts (9 999) gets one request to correct it;
    corrected — the model's text with the prompt's version; wrong twice — None (the rules' text stays), no
    third call."""
    from app.core.db import get_sessionmaker

    facts = {
        "count_on": "2026-10-22",
        "days_left": 2,
        "last_count": "2026-09-21",
        "products": [{"code": "P2", "name": "Товар P2", "reason": "shortage", "diff_rub": "200"}],
    }
    rules = texts.inventory(facts)[1]
    with get_sessionmaker()() as s:
        ctx = system_context(s, network.a.id)
        wrong = FakeModel()
        wrong.replies += [_model("Недостача 9 999 ₽ — начните с нее.")] * 3
        assert agent_writer.writer(Gateway(wrong), ctx)("inventory_prep", facts, rules) is None
        assert len(wrong.requests) == 2  # the first answer and one correction, no more
        assert "9999" in json.dumps(wrong.requests[1].messages, ensure_ascii=False).replace(" ", "")
        fixed = FakeModel()
        fixed.replies += [_model("Недостача 9 999 ₽."), _model("Недостача 200 ₽ — начните с нее.")]
        assert agent_writer.writer(Gateway(fixed), ctx)("inventory_prep", facts, rules) == (
            "Недостача 200 ₽ — начните с нее.",
            1,
        )
        # Strict: a small count not in the facts is a figure too («7 позиций» while the list has 1).
        counts = FakeModel()
        counts.replies += [_model("Пересчитайте 7 позиций.")] * 2
        assert agent_writer.writer(Gateway(counts), ctx)("inventory_prep", facts, rules) is None
        # The model off (no reply): None, not an error.
        assert agent_writer.writer(Gateway(FakeModel()), ctx)("inventory_prep", facts, rules) is None


def test_the_worker_runs_the_agents_every_morning_at_0547_utc(
    world: World, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-AG-24: the cron job `morning_agents` at 05:47 UTC (08:47 Moscow, Q38) every day, with or without the
    demo rebuild; it runs every network with the model's writer when the gateway is on."""
    import asyncio

    from app import worker

    job = {j.name: j for j in worker.cron_jobs()}["cron:morning_agents"]
    assert job.hour == {5} and job.minute == {47} and job.weekday is None and job.day is None
    fake = FakeModel()
    fake.replies += [_model("Посмотрите это сообщение и решите, что делать.")] * 50
    monkeypatch.setattr(worker, "get_gateway", lambda: Gateway(fake))
    monkeypatch.setattr(worker, "get_today", lambda: TODAY)
    asyncio.run(worker.morning_agents({}))
    notes = _notes(owner_engine)
    assert {n.agent for n in notes} == {"inventory_prep", "task_due", "task_stuck", "data_check"}
    assert all(n.source == "model" and n.items == texts.by_rules(n.agent, n.facts)[2] for n in notes)


def test_run_agents_from_the_command_line_is_idempotent(
    world: World, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """TC-AG-25: `python -m app.cli run-agents` — the morning pass by hand, texts by rules without the model;
    it prints how many notes wait; a second run writes nothing new."""
    from app import cli

    monkeypatch.setattr(cli, "date_today", lambda: TODAY)
    monkeypatch.setattr("sys.argv", ["app.cli", "run-agents"])
    cli.main()
    with Session(owner_engine) as s:
        waiting = s.execute(
            select(func.count()).select_from(AgentNote).where(AgentNote.status == "new")
        ).scalar()
        total = s.execute(select(func.count()).select_from(AgentNote)).scalar()
    assert capsys.readouterr().out == f"agents' notes waiting: {waiting}\n" and waiting and waiting >= 5
    cli.main()
    assert capsys.readouterr().out == f"agents' notes waiting: {waiting}\n"
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(AgentNote)).scalar() == total
    assert all(n.source == "rules" for n in _notes(owner_engine))


def test_a_deadline_moves_up_to_ninety_days_ahead(world: World, network: Network) -> None:
    """TC-AG-07 (edge): exactly 90 days ahead and today itself are allowed; the move is audited."""
    from app.core.db import get_sessionmaker
    from app.tasks.service import move_due
    from app.tenancy.context import load_access_context

    with get_sessionmaker()() as s:
        admin = load_access_context(s, network.a.users["admin@a.ru"], world.a)
        assert admin is not None
        assert move_due(s, admin, world.stuck.id, TODAY + timedelta(days=90), today=TODAY).due_on == date(
            2027, 1, 18
        )  # 20.10.2026 + 90 days: 11 left in October + 30 + 31 = 72 → 18 more days of January
        assert move_due(s, admin, world.stuck.id, TODAY, today=TODAY).due_on == TODAY
        s.rollback()


def test_a_list_for_a_count_that_has_passed_is_not_taken_into_work(
    world: World, client: TestClient, owner_engine: Engine
) -> None:
    """TC-AG-27: the list asked for today (20.10) and answered tomorrow, before the morning run expired it:
    «Создать задачу» — 422 «День пересчета уже прошел», no task; «Не нужно» still works."""
    director2 = login(client, "director2@a.ru")
    body = {"restaurant_id": str(world.a2), "count_on": TODAY.isoformat()}
    note = client.post("/api/agents/inventory-prep", json=body, headers=director2).json()
    app.dependency_overrides[get_today] = lambda: TODAY + timedelta(days=1)
    late = client.post(f"/api/agents/notes/{note['id']}/accept", headers=director2)
    assert late.status_code == 422 and "уже прошел" in late.json()["detail"]
    with Session(owner_engine) as s:
        assert not s.execute(select(Task).where(Task.title == note["action_title"])).first()
    assert client.post(f"/api/agents/notes/{note['id']}/dismiss", headers=director2).status_code == 200
