"""Agents, stage 10 (ADR 0010): the shortage story, the supplier request, the transfer and the HQ's weekly
agenda — every note to the HQ, the reasons and numbers from the code, a person decides.

Network A: A1 overuses cheese (a confirmed M1 finding, a new supplier in September, nothing written off), the
network's cheese supplier billed above the contract, A1's pasta runs out before the delivery while A2 has
plenty, a task of A2 is late and a check waits to be launched."""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents import service, story, texts
from app.agents.models import AgentNote
from app.catalog.models import ContractPrice, Product, Supplier
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.experiments.models import Experiment
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.main import app
from app.operations.models import Receipt, StockBalance, Transfer
from app.tasks.models import Task
from tests.conftest import Network, login

TODAY = date(2026, 10, 20)  # a Tuesday: the agenda of the week of 19.10
STAGE_10 = ("shortage_story", "supplier_claim", "transfer", "hq_agenda")


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _batch(s: Session, tenant: UUID, restaurant: UUID, template: str) -> UUID:
    b = ImportBatch(
        tenant_id=tenant,
        restaurant_id=restaurant,
        template=template,
        filename=f"{template}.csv",
        sha256=uuid4().hex * 2,
        raw=b"",
        status="published",
    )
    s.add(b)
    s.flush()
    return b.id


def _finding(tenant: UUID, restaurant: UUID | None, key: str, title: str, **kw: Any) -> Finding:
    module = key.split(":")[0]
    return Finding(
        tenant_id=tenant,
        restaurant_id=restaurant,
        kind="problem",
        process="purchasing" if module == "M3" else "production",
        title=title,
        found_on=TODAY,
        key=key,
        module=module,
        review_status=kw.pop("review_status", "confirmed"),
        **kw,
    )


class World:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        a = network.a
        self.tenant = a.id
        self.a1, self.a2, self.a3 = a.restaurants["A1"], a.restaurants["A2"], a.restaurants["A3"]
        with Session(owner_engine, expire_on_commit=False) as s, s.begin():
            cheese = Product(tenant_id=a.id, code="P1", name="Сыр", base_unit="kg")
            pasta = Product(tenant_id=a.id, code="P2", name="Паста", base_unit="kg")
            old = Supplier(tenant_id=a.id, code="S1", name="Сырный дом")
            new = Supplier(tenant_id=a.id, code="S2", name="Новый сыр")
            s.add_all([cheese, pasta, old, new])
            s.flush()
            self.cheese, self.pasta = cheese.id, pasta.id
            b1, b2 = (_batch(s, a.id, r, "receipts") for r in (self.a1, self.a2))

            def receipt(
                r: UUID, b: UUID, day: date, p: UUID, sup: UUID, qty: str, amount: str, doc: str
            ) -> None:
                s.add(
                    Receipt(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=b,
                        day=day,
                        doc_no=doc,
                        supplier_id=sup,
                        product_id=p,
                        qty=Decimal(qty),
                        amount=Decimal(amount),
                    )
                )

            # № 2: cheese of A1 — S1 in August, S2 in September; nothing written off; the overuse doubles.
            receipt(self.a1, b1, date(2026, 8, 10), cheese.id, old.id, "100", "50000", "А-1")
            receipt(self.a1, b1, date(2026, 9, 10), cheese.id, new.id, "110", "55000", "Б-1")
            s.add(
                _finding(
                    a.id,
                    self.a1,
                    "M1:A1:P1",
                    "Перерасход по техкарте: Сыр",
                    effect_rub_month=Decimal("15000.00"),
                    period_from=date(2026, 8, 1),
                    period_to=date(2026, 9, 30),
                    evidence={
                        "product": "P1",
                        "benchmark": "0.02",
                        "periods": [
                            {
                                "from": "2026-08-01",
                                "to": "2026-08-31",
                                "share": "0.05",
                                "actual": "105",
                                "theory": "100",
                                "write_off": "0",
                            },
                            {
                                "from": "2026-09-01",
                                "to": "2026-09-30",
                                "share": "0.10",
                                "actual": "110",
                                "theory": "100",
                                "write_off": "0",
                            },
                        ],
                    },
                )
            )
            # Too small for a story, and below the recipes: no story either.
            s.add(
                _finding(
                    a.id,
                    self.a2,
                    "M1:A2:P1",
                    "Мелкий перерасход",
                    effect_rub_month=Decimal(5000),
                    evidence={"product": "P1", "periods": [{"from": "2026-09-01"}]},
                )
            )
            s.add(
                _finding(
                    a.id,
                    self.a3,
                    "M1:A3:P1:under",
                    "Ниже техкарты",
                    effect_rub_month=Decimal(20000),
                    evidence={"product": "P1", "periods": [{"from": "2026-09-01"}]},
                )
            )

            # № 3: the network's contract with S1 is 500 ₽/кг; two of three September invoices are above it.
            receipt(self.a1, b1, date(2026, 9, 5), cheese.id, old.id, "10", "5500", "Н-1")
            receipt(self.a2, b2, date(2026, 9, 12), cheese.id, old.id, "5", "2500", "Н-2")
            receipt(self.a2, b2, date(2026, 9, 20), cheese.id, old.id, "4", "2200", "Н-3")
            # From 16.09 the contract is 540 ₽: Н-3 (550) is above it, Н-4 (545) within its 1 % rounding.
            receipt(self.a2, b2, date(2026, 9, 25), cheese.id, old.id, "4", "2180", "Н-4")
            s.add(
                ContractPrice(
                    tenant_id=a.id,
                    supplier_id=old.id,
                    product_id=cheese.id,
                    price=Decimal(500),
                    valid_from=date(2026, 8, 1),
                    valid_to=date(2026, 9, 15),
                )
            )
            s.add(
                ContractPrice(
                    tenant_id=a.id,
                    supplier_id=old.id,
                    product_id=cheese.id,
                    price=Decimal(540),
                    valid_from=date(2026, 9, 16),
                )
            )
            s.add(
                _finding(
                    a.id,
                    None,
                    "M3:net:P1:contract",
                    "Цена выше договорной: Сыр",
                    effect_rub_month=Decimal("700.00"),
                    period_from=date(2026, 9, 1),
                    period_to=date(2026, 9, 30),
                    evidence={
                        "kind": "contract",
                        "product": "P1",
                        "supplier": "Сырный дом",
                        "contract_price": "500.00",
                    },
                )
            )
            # A price jump of S2's pasta at A1 since 15.09 — confirmed: a request; the same, pending: nothing.
            receipt(self.a1, b1, date(2026, 9, 10), pasta.id, new.id, "10", "1000", "П-1")
            receipt(self.a1, b1, date(2026, 9, 20), pasta.id, new.id, "10", "1200", "П-2")
            jump = {
                "kind": "jump",
                "product": "P2",
                "supplier": "Новый сыр",
                "price_before": "100.00",
                "since": "2026-09-15",
            }
            s.add(
                _finding(
                    a.id,
                    self.a1,
                    "M3:A1:P2:jump",
                    "Цена выросла: Паста",
                    effect_rub_month=Decimal(800),
                    period_from=date(2026, 9, 15),
                    period_to=date(2026, 9, 30),
                    evidence=jump,
                )
            )
            s.add(
                _finding(
                    a.id,
                    self.a3,
                    "M3:A3:P2:jump",
                    "Цена выросла: Паста (А3)",
                    review_status="pending",
                    effect_rub_month=Decimal(800),
                    period_from=date(2026, 9, 15),
                    period_to=date(2026, 9, 30),
                    evidence=jump,
                )
            )

            # № 5: A1's pasta runs out on 20.10, the delivery is on 22.10: two days of need, 2 + 3 kg.
            s.add(
                _finding(
                    a.id,
                    self.a1,
                    "M6:A1:P2:shortage",
                    "Закончится до поставки: Паста",
                    review_status="pending",
                    evidence={
                        "kind": "shortage",
                        "product": "P2",
                        "zero_day": "2026-10-20",
                        "next_delivery": "2026-10-22",
                        "data_until": "2026-10-19",
                        "need_by_weekday": ["1", "2", "3", "4", "5", "6", "7"],
                    },
                )
            )
            # A2 has 20 kg on 19.10 and buys 1 kg a day (28 kg over 4 weeks); A3's count is too old.
            for day in range(28):
                receipt(
                    self.a2, b2, date(2026, 10, 19) - timedelta(days=day), pasta.id, old.id, "1", "100", ""
                )
            stock2, stock3 = (
                _batch(s, a.id, self.a2, "stock_balances"),
                _batch(s, a.id, self.a3, "stock_balances"),
            )
            s.add(
                StockBalance(
                    tenant_id=a.id,
                    restaurant_id=self.a2,
                    import_batch_id=stock2,
                    day=date(2026, 10, 19),
                    product_id=pasta.id,
                    qty=Decimal(20),
                )
            )
            s.add(
                StockBalance(
                    tenant_id=a.id,
                    restaurant_id=self.a3,
                    import_batch_id=stock3,
                    day=date(2026, 10, 10),
                    product_id=pasta.id,
                    qty=Decimal(100),
                )
            )

            # № 8: a task of A2 three days late, a check waiting to be launched.
            s.add(
                Task(
                    tenant_id=a.id,
                    restaurant_id=self.a2,
                    title="Сверить остатки",
                    checklist=[],
                    checklist_done=[],
                    assigned_by="hq",
                    created_on=date(2026, 10, 1),
                    due_on=date(2026, 10, 17),
                    status="assigned",
                )
            )
            s.add(
                Experiment(
                    tenant_id=a.id,
                    title="Порции сыра по весам",
                    hypothesis="…",
                    metric="…",
                    test_restaurant_ids=[self.a1],
                    starts_on=TODAY,
                    ends_on=TODAY + timedelta(days=28),
                    expected_rub_month=Decimal(1000),
                    status="proposed",
                )
            )


@pytest.fixture
def world(network: Network, owner_engine: Engine) -> World:
    return World(network, owner_engine)


def _notes(owner_engine: Engine, agent: str) -> list[AgentNote]:
    with Session(owner_engine) as s:
        return list(
            s.execute(select(AgentNote).where(AgentNote.agent == agent).order_by(AgentNote.key)).scalars()
        )


def _api(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    r = client.get("/api/agents/notes", headers=headers)
    assert r.status_code == 200, r.text
    return {n["agent"] + ":" + (n["restaurant_code"] or "net"): n for n in r.json() if n["agent"] in STAGE_10}


# ------------------------------------------------------------------ № 2: the shortage story


def test_a_large_shortage_gets_its_timeline_and_versions(world: World, owner_engine: Engine) -> None:
    """TC-AG-28: a confirmed M1 overuse of 15 000 ₽ — the counts' periods with what was bought from whom,
    the versions by rules (a new supplier, nothing written off, a growing overuse) and what to check; too
    small and «below the recipes» get none; to the HQ, nothing to press."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "shortage_story")
    assert (note.audience, note.restaurant_id, note.proposal) == ("hq", world.a1, None)
    assert note.facts["versions"] == ["supplier", "no_write_offs", "growing"]
    assert [p["bought"] for p in note.facts["periods"]] == [
        {"Сырный дом": "100"},
        {"Новый сыр": "110", "Сырный дом": "10"},  # and the invoice of the claim below
    ]
    assert note.title == "Недостача: сыр в «Сеть А A1» — версии"
    assert note.items[1] == (
        "01.09–30.09: по пересчетам 110 кг, по техкартам 100 кг (+10%), списано 0 кг; "
        "закуплено 110 кг у «Новый сыр», 10 кг у «Сырный дом»"
    )
    assert "1) сменился или добавился поставщик" in note.text and "Вывод — за аналитиком." in note.text
    assert "по сети обычно +2%" in note.text


def test_the_story_versions_follow_the_timeline() -> None:
    """TC-AG-28: moved out to other restaurants is a version; with nothing particular — the portions."""

    def period(
        share: str, written: str = "1", out: str = "0", bought: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return {"share": share, "written_off": written, "moved_out": out, "bought": bought or {"S": "1"}}

    assert story.versions([period("5", out="2"), period("5")], Decimal("0.02")) == ["moved_out", "portions"]
    assert story.versions([period("1"), period("1")], Decimal("0.02")) == ["portions"]
    many = [period("5", "0", "1", {"S1": "1"}), period("10", "0", "0", {"S2": "1"})]
    assert story.versions(many, Decimal("0.02")) == ["supplier", "no_write_offs", "moved_out"]


# ------------------------------------------------------------------ № 3: the supplier request


def test_a_claim_lists_the_invoices_above_the_contract(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-29: the invoices above the contract by number, the overpayment of each and in all; one at the
    contract price is not listed; a confirmed jump gives a request with the price before and after, a pending
    one nothing. «Отправлено» records the HQ admin's decision and makes no task; the analyst only reads."""
    service.run_all(TODAY)
    claim, jump = _notes(owner_engine, "supplier_claim")
    assert claim.key == "supplier_claim:M3:A1:P2:jump" or jump.key == "supplier_claim:M3:A1:P2:jump"
    if claim.key.endswith(":jump"):
        claim, jump = jump, claim
    # Each invoice against the contract of its day (500, then 540), Н-4 within the 1 % (backend review, p. 2)
    assert claim.restaurant_id is None and claim.facts["extra"] == "540.00"
    assert [(x["doc"], x["reference"], x["extra"]) for x in claim.facts["invoices"]] == [
        ("Н-1", "500.00", "500.00"),
        ("Н-3", "540.00", "40.00"),
    ]
    assert "цена товара «Сыр» — от 500\u00a0₽ до 540\u00a0₽/кг" in claim.text
    assert claim.items[0] == "№ Н-1 от 05.09, Сеть А A1: 10 кг по 550\u00a0₽ — переплата 500\u00a0₽"
    assert claim.title == "Претензия «Сырный дом»: сыр дороже договора"
    assert "(п. ___)" in claim.text and "Переплата — 540\u00a0₽" in claim.text
    assert jump.facts["growth_pct"] == "20.0" and [x["doc"] for x in jump.facts["invoices"]] == ["П-2"]
    assert "выросла с 100\u00a0₽ до 120\u00a0₽/кг (+20,0%)" in jump.text

    notes = _api(client, login(client, "admin@a.ru"))
    assert (
        notes["supplier_claim:net"]["action"] == "claim"
        and notes["supplier_claim:net"]["restaurant_name"] is None
    )
    analyst = login(client, "analyst@a.ru")
    assert client.post(f"/api/agents/notes/{claim.id}/accept", headers=analyst).status_code == 403
    admin = login(client, "admin@a.ru")
    before = _tasks(owner_engine)
    sent = client.post(f"/api/agents/notes/{claim.id}/accept", headers=admin)
    assert sent.status_code == 200 and sent.json()["status"] == "accepted"
    assert sent.json()["result_task_id"] is None and _tasks(owner_engine) == before


def _tasks(owner_engine: Engine) -> list[tuple[str, UUID, date]]:
    with Session(owner_engine) as s:
        return [
            (t.title, t.restaurant_id, t.due_on)
            for t in s.execute(select(Task).order_by(Task.title)).scalars()
        ]


# ------------------------------------------------------------------ № 5: the transfer


def test_a_transfer_bridges_the_days_to_the_delivery(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-30: the need of the days to the delivery (2 + 3 kg), from the restaurant with the most to spare
    by its fresh «Остатки на дату» (A3's are too old); «Поставить задачи» — one task to hand over, one to take
    in, both by the day it runs out; only the HQ admin."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "transfer")
    assert (note.restaurant_id, note.facts["qty"], note.facts["from"], note.facts["from_daily"]) == (
        world.a1,
        "5",
        "Сеть А A2",
        "1",
    )
    assert texts.by_rules("transfer", note.facts)[1] == (
        "В «Сеть А A1» паста по расчету закончится 20.10, поставка — 22.10: до нее нужно 5 кг. "
        "В «Сеть А A2» по остаткам на 19.10 — 20 кг при закупке ≈ 1 кг в день: после передачи у них "
        "останется запас больше чем на 3 дня. Передать 5 кг до 20.10."
    )
    planned = _api(client, login(client, "admin@a.ru"))["transfer:A1"]["action_tasks"]
    assert [(t["restaurant_id"], t["title"]) for t in planned] == [
        (str(world.a2), "Передать в «Сеть А A1»: паста, 5 кг"),
        (str(world.a1), "Принять из «Сеть А A2»: паста, 5 кг"),
    ]
    director = login(client, "director1@a.ru")
    assert client.post(f"/api/agents/notes/{note.id}/accept", headers=director).status_code == 404
    r = client.post(f"/api/agents/notes/{note.id}/accept", headers=login(client, "admin@a.ru"))
    assert r.status_code == 200, r.text
    assert [(t, rid, due) for t, rid, due in _tasks(owner_engine) if "паста" in t] == [
        ("Передать в «Сеть А A1»: паста, 5 кг", world.a2, TODAY),
        ("Принять из «Сеть А A2»: паста, 5 кг", world.a1, TODAY),
    ]


def test_no_transfer_from_a_restaurant_short_itself_or_without_enough(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-30: a giver short of the same product itself is not asked; when nobody has enough, no note."""
    with Session(owner_engine) as s, s.begin():
        s.add(
            _finding(
                world.tenant,
                world.a2,
                "M6:A2:P2:shortage",
                "Закончится до поставки: Паста (А2)",
                review_status="pending",
                evidence={
                    "kind": "shortage",
                    "product": "P2",
                    "zero_day": "2026-10-25",
                    "next_delivery": "2026-10-26",
                    "data_until": "2026-10-19",
                    "need_by_weekday": ["1"] * 7,
                },
            )
        )
    service.run_all(TODAY)
    assert [n.status for n in _notes(owner_engine, "transfer")] == []
    with Session(owner_engine) as s, s.begin():
        for f in s.execute(select(Finding).where(Finding.key == "M6:A2:P2:shortage")).scalars():
            s.delete(f)
        s.execute(select(StockBalance)).scalars()
        for b in s.execute(select(StockBalance).where(StockBalance.restaurant_id == world.a2)).scalars():
            b.qty = Decimal(7)  # 7 − 3 days × 1 kg = 4 kg to spare, 5 needed
    service.run_all(TODAY)
    assert _notes(owner_engine, "transfer") == []


# ------------------------------------------------------------------ № 8: the agenda


def test_the_weekly_agenda_is_the_networks_and_lives_monday_to_friday(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-31: one note of the whole network for the week: the most expensive confirmed findings (a pending
    one is not on it), the late task, the check to launch; computed again each morning; gone at the weekend; a
    new one next Monday. No director sees it."""
    service.run_all(TODAY)
    (agenda,) = _notes(owner_engine, "hq_agenda")
    assert (agenda.key, agenda.restaurant_id, agenda.for_date) == (
        "hq_agenda:2026-10-19",
        None,
        date(2026, 10, 19),
    )
    assert [x["title"] for x in agenda.facts["findings"]][:2] == [
        "Ниже техкарты",
        "Перерасход по техкарте: Сыр",
    ]
    assert "Цена выросла: Паста (А3)" not in [x["title"] for x in agenda.facts["findings"]]
    assert agenda.facts["late"] == [{"title": "Сверить остатки", "place": "Сеть А A2", "days": 3}]
    assert agenda.facts["checks"] == ["Порции сыра по весам"]
    assert "Просрочена: Сверить остатки — Сеть А A2, на 3 дн." in agenda.items
    assert agenda.title == "Повестка планерки: неделя с 19.10"
    notes = _api(client, login(client, "admin@a.ru"))
    assert notes["hq_agenda:net"]["restaurant_id"] is None and notes["hq_agenda:net"]["action"] is None

    service.run_all(date(2026, 10, 21))  # Wednesday: the same note, the late task a day later
    (again,) = _notes(owner_engine, "hq_agenda")
    assert again.id == agenda.id and again.facts["late"][0]["days"] == 4
    service.run_all(date(2026, 10, 24))  # Saturday
    assert [n.status for n in _notes(owner_engine, "hq_agenda")] == ["expired"]
    service.run_all(date(2026, 10, 26))  # the next Monday
    assert [(n.key, n.status) for n in _notes(owner_engine, "hq_agenda")] == [
        ("hq_agenda:2026-10-19", "expired"),
        ("hq_agenda:2026-10-26", "new"),
    ]


# ------------------------------------------------------------------ who sees them


def test_no_director_and_no_other_network_sees_the_hqs_notes(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-32: all four agents write to the HQ: a director of A1 sees none of them — not the story about
    their own restaurant, not the agenda of the whole network; another network sees nothing of A."""
    service.run_all(TODAY)
    hq = _api(client, login(client, "admin@a.ru"))
    assert set(hq) == {
        "shortage_story:A1",
        "supplier_claim:net",
        "supplier_claim:A1",
        "transfer:A1",
        "hq_agenda:net",
    }
    assert _api(client, login(client, "director1@a.ru")) == {}
    assert _api(client, login(client, "admin@b.ru")) == {}
    for n in hq.values():
        r = client.post(f"/api/agents/notes/{n['id']}/dismiss", headers=login(client, "director1@a.ru"))
        assert r.status_code == 404


def test_one_giver_is_not_promised_twice(world: World, owner_engine: Engine) -> None:
    """TC-AG-30 (backend review of stage 10, p. 1): A2 can spare 16 kg (20 on 19.10 less 3 days and the
    day to the transfer, at 1 kg a day); A1 takes 5 of them, so A3 asking for 12 gets no note."""
    with Session(owner_engine) as s, s.begin():
        s.add(
            _finding(
                world.tenant,
                world.a3,
                "M6:A3:P2:shortage",
                "Закончится до поставки: Паста (А3)",
                review_status="pending",
                evidence={
                    "kind": "shortage",
                    "product": "P2",
                    "zero_day": "2026-10-20",
                    "next_delivery": "2026-10-21",
                    "data_until": "2026-10-19",
                    "need_by_weekday": ["12"] * 7,
                },
            )
        )
    service.run_all(TODAY)
    assert [n.key for n in _notes(owner_engine, "transfer")] == ["transfer:M6:A1:P2:shortage"]


# ------------------------------------------------------------------ test engineer after the stage 10 review


def _strict(tenant: UUID, today: date) -> None:
    """One network's pass with its failure raised: `run_all` logs a failed network and goes on, so a «no note»
    after it could be a crash."""
    with get_sessionmaker()() as s:
        service.run_network(s, tenant, today)
        s.commit()


def _evidence(owner_engine: Engine, key: str, **changes: Any) -> None:
    with Session(owner_engine) as s, s.begin():
        f = s.execute(select(Finding).where(Finding.key == key)).scalar_one()
        f.evidence = {**(f.evidence or {}), **changes}


def test_the_agenda_on_friday_at_the_weekend_and_with_nothing_to_say(
    network: Network, world: World, owner_engine: Engine
) -> None:
    """TC-AG-31: Friday still has the week's agenda (the late task due 17.10 is 6 days late on 23.10), Sunday
    none; a week with nothing to say has no agenda — the one of the week expires; network B, empty, never has
    one."""
    _strict(world.tenant, date(2026, 10, 23))  # Friday
    (friday,) = _notes(owner_engine, "hq_agenda")
    assert (friday.key, friday.status, friday.for_date) == ("hq_agenda:2026-10-19", "new", date(2026, 10, 19))
    assert friday.facts["late"] == [{"title": "Сверить остатки", "place": "Сеть А A2", "days": 6}]
    _strict(world.tenant, date(2026, 10, 25))  # Sunday
    assert [n.status for n in _notes(owner_engine, "hq_agenda")] == ["expired"]

    _strict(world.tenant, date(2026, 10, 27))  # Tuesday of the next week: a new agenda
    with Session(owner_engine) as s, s.begin():  # then everything is done: nothing to put on it
        for model in (Task, Experiment, Finding):
            for row in s.execute(select(model)).scalars():
                s.delete(row)
    _strict(world.tenant, date(2026, 10, 28))
    assert [(n.key, n.status) for n in _notes(owner_engine, "hq_agenda")] == [
        ("hq_agenda:2026-10-19", "expired"),
        ("hq_agenda:2026-10-26", "expired"),
    ]
    _strict(network.b.id, date(2026, 10, 28))
    with Session(owner_engine) as s:
        b = select(AgentNote.agent).where(AgentNote.tenant_id == network.b.id)
        assert "hq_agenda" not in s.execute(b).scalars().all()  # B has its «нет выгрузок» notes only


def test_the_agenda_counts_beyond_its_top_five(world: World, owner_engine: Engine) -> None:
    """TC-AG-31: at most five findings and five late tasks on the list, the text counts every late task; a
    done task is not late."""
    with Session(owner_engine) as s, s.begin():
        for i in range(6):
            s.add(
                Task(
                    tenant_id=world.tenant,
                    restaurant_id=world.a3,
                    title=f"Задача {i}",
                    checklist=[],
                    checklist_done=[],
                    assigned_by="hq",
                    created_on=date(2026, 10, 1),
                    due_on=date(2026, 10, 18),
                    status="done" if i == 5 else "in_progress",
                    done_on=date(2026, 10, 17) if i == 5 else None,
                )
            )
    _strict(world.tenant, TODAY)
    (agenda,) = _notes(owner_engine, "hq_agenda")
    assert len(agenda.facts["findings"]) == 5 and len(agenda.facts["late"]) == 5
    assert agenda.facts["late_total"] == 6  # «Сверить остатки» and «Задача 0…4»
    assert agenda.facts["late"][0]["title"] == "Сверить остатки"  # the most overdue first
    assert "просроченных задач — 6" in agenda.text


def test_a_claim_skips_an_invoice_with_no_contract_on_its_day(world: World, owner_engine: Engine) -> None:
    """TC-AG-29: without the contract from 16.09 the invoices Н-3 and Н-4 have no agreed price — they are not
    in the claim (no price to compare with), Н-1 is (550 − 500) × 10 = 500 ₽; the text names one price. With
    no contract on any invoice's day there is no claim at all."""
    with Session(owner_engine) as s, s.begin():
        for c in s.execute(select(ContractPrice).where(ContractPrice.price == 540)).scalars():
            s.delete(c)
    _strict(world.tenant, TODAY)
    (claim,) = [n for n in _notes(owner_engine, "supplier_claim") if n.restaurant_id is None]
    assert [(x["doc"], x["extra"]) for x in claim.facts["invoices"]] == [("Н-1", "500.00")]
    assert claim.facts["extra"] == "500.00"
    assert "цена товара «Сыр» — 500 ₽/кг" in claim.text and "в 1 накладной" in claim.text

    with Session(owner_engine) as s, s.begin():
        for c in s.execute(select(ContractPrice)).scalars():
            c.valid_from, c.valid_to = date(2026, 9, 6), date(2026, 9, 11)  # between Н-1 and Н-2
    _strict(world.tenant, TODAY)
    assert [n.status for n in _notes(owner_engine, "supplier_claim") if n.restaurant_id is None] == [
        "expired"
    ]


def test_no_claim_when_two_suppliers_share_the_name(world: World, owner_engine: Engine) -> None:
    """TC-AG-29 (backend review of stage 10, p. 3): a second «Сырный дом» in the network — the finding cannot
    tell which one, so no letter; the jump of «Новый сыр» still has its request."""
    with Session(owner_engine) as s, s.begin():
        s.add(Supplier(tenant_id=world.tenant, code="S3", name="Сырный дом"))
    _strict(world.tenant, TODAY)
    assert [n.key for n in _notes(owner_engine, "supplier_claim")] == ["supplier_claim:M3:A1:P2:jump"]


def test_a_request_follows_the_networks_price_and_averages_every_invoice(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-29 (backend review of stage 10, p. 2): the network's prices moved +10 %, so the expected price is
    100 × 1,1 = 110 ₽. П-2 at 120 ₽ is above it: (120 − 110) × 10 = 100 ₽; П-3 at 100 ₽ is not listed. The
    price after the rise is the average of both: (1200 + 1000) / 20 = 110 ₽, +10,0 % on 100 ₽."""
    _evidence(owner_engine, "M3:A1:P2:jump", network_growth="0.1")
    with Session(owner_engine) as s, s.begin():
        batch = _batch(s, world.tenant, world.a1, "receipts")
        new = s.execute(select(Supplier).where(Supplier.code == "S2")).scalar_one()
        s.add(
            Receipt(
                tenant_id=world.tenant,
                restaurant_id=world.a1,
                import_batch_id=batch,
                day=date(2026, 9, 25),
                doc_no="П-3",
                supplier_id=new.id,
                product_id=world.pasta,
                qty=Decimal(10),
                amount=Decimal(1000),
            )
        )
    _strict(world.tenant, TODAY)
    (jump,) = [n for n in _notes(owner_engine, "supplier_claim") if n.key.endswith(":jump")]
    assert [(x["doc"], x["reference"], x["extra"]) for x in jump.facts["invoices"]] == [
        ("П-2", "110.00", "100.00")
    ]
    assert (jump.facts["price"], jump.facts["growth_pct"], jump.facts["extra"]) == (
        "110.00",
        "10.0",
        "100.00",
    )
    assert "выросла с 100 ₽ до 110 ₽/кг (+10,0%)" in jump.text
    assert "разница — 100 ₽ в 1 накладной" in jump.text


def test_a_transfer_when_the_day_it_runs_out_has_passed(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-30: the pasta ran out on 16.10 by the forecast; the need counts from today, 20.10 (Tuesday 0,75 +
    Wednesday 1 = 1,75 → 1,8 kg up to the 0,1 kg one weighs), not from 16.10 (that would be 5,25); the text
    says «закончилась», both tasks are due today."""
    _evidence(
        owner_engine,
        "M6:A1:P2:shortage",
        zero_day="2026-10-16",
        need_by_weekday=["0.5", "0.75", "1", "1", "1", "1", "1"],
    )
    _strict(world.tenant, TODAY)
    (note,) = _notes(owner_engine, "transfer")
    assert (note.facts["qty"], note.facts["by"], note.for_date) == ("1.8", "2026-10-20", TODAY)
    assert texts.by_rules("transfer", note.facts)[1].startswith(
        "В «Сеть А A1» паста по расчету закончилась 16.10, поставка — 22.10: до нее нужно 1,8 кг."
    )
    r = client.post(f"/api/agents/notes/{note.id}/accept", headers=login(client, "admin@a.ru"))
    assert r.status_code == 200, r.text
    assert {due for t, _, due in _tasks(owner_engine) if "паста" in t} == {TODAY}


@pytest.mark.parametrize(
    ("zero_day", "delivery"),
    [("2026-10-22", "2026-10-22"), ("2026-10-23", "2026-10-22"), ("2026-10-15", "2026-10-19")],
)
def test_no_transfer_when_the_delivery_comes_first(
    world: World, owner_engine: Engine, zero_day: str, delivery: str
) -> None:
    """TC-AG-30: the delivery comes on the day it runs out, before it, or has come already (both past): there
    are no days to bridge — no note, while the other agents of the pass still write theirs."""
    _evidence(owner_engine, "M6:A1:P2:shortage", zero_day=zero_day, next_delivery=delivery)
    _strict(world.tenant, TODAY)
    assert _notes(owner_engine, "transfer") == []
    assert len(_notes(owner_engine, "hq_agenda")) == 1


def test_the_need_is_rounded_up_to_what_one_weighs_or_counts() -> None:
    """TC-AG-30: 7 days × 0,3 = 2,1 — 3 шт (a piece is not cut), 2,1 kg and l; 3 days × 1 шт = 3 шт exactly;
    0,01 kg → 0,1 kg; an unknown unit is weighed by 0,1."""
    from app.agents import transfers

    week = {"need_by_weekday": ["0.3"] * 7}
    start, delivery = date(2026, 10, 20), date(2026, 10, 27)
    assert transfers._need(week, start, delivery, "pcs") == Decimal(3)
    assert transfers._need(week, start, delivery, "kg") == Decimal("2.1")
    assert transfers._need(week, start, delivery, "l") == Decimal("2.1")
    assert transfers._need(week, start, delivery, "упак") == Decimal("2.1")
    assert transfers._need({"need_by_weekday": ["1"] * 7}, start, start + timedelta(days=3), "pcs") == 3
    assert transfers._need(
        {"need_by_weekday": ["0.01"] * 7}, start, start + timedelta(days=1), "kg"
    ) == Decimal("0.1")


def test_the_story_counts_what_was_moved_out_and_in(world: World, owner_engine: Engine) -> None:
    """TC-AG-28: transfers in the database — A1 gave A2 4 kg on 15.09 and got 1,5 kg from A2 on 20.08; one
    of 7 kg on 05.10 is outside the finding's periods. The periods show them; «moved out» is a version, the
    third — the growing overuse does not fit (three at most)."""
    with Session(owner_engine) as s, s.begin():
        out1, in1 = (_batch(s, world.tenant, r, "transfers") for r in (world.a1, world.a2))
        for sender, batch, receiver, day, qty in (
            (world.a1, out1, world.a2, date(2026, 9, 15), "4"),
            (world.a2, in1, world.a1, date(2026, 8, 20), "1.5"),
            (world.a1, out1, world.a3, date(2026, 10, 5), "7"),
        ):
            s.add(
                Transfer(
                    tenant_id=world.tenant,
                    restaurant_id=sender,
                    import_batch_id=batch,
                    day=day,
                    to_restaurant_id=receiver,
                    product_id=world.cheese,
                    qty=Decimal(qty),
                )
            )
    _strict(world.tenant, TODAY)
    (note,) = _notes(owner_engine, "shortage_story")
    assert [(p["moved_out"], p["moved_in"]) for p in note.facts["periods"]] == [("0", "1.5"), ("4", "0")]
    assert note.facts["versions"] == ["supplier", "no_write_offs", "moved_out"]
    assert note.items[0].endswith("закуплено 100 кг у «Сырный дом»; получено 1,5 кг")
    assert note.items[1].endswith("; передано в другие рестораны 4 кг")
    assert "3) товар уходил перемещениями" in note.text and "растет" not in note.text


def test_the_texts_agree_with_their_numbers() -> None:
    """TC-AG-34: «1 день, 3 дня, 5 дней, 11 дней, 21 день, 112 дней», the same for positions and steps;
    «в 1 накладной», «в 3 накладных», «в 21 накладной»; a transfer in pieces says «шт»."""
    days = ("день", "дня", "дней")
    assert [texts._count(n, days) for n in (1, 3, 5, 11, 12, 14, 21, 22, 25, 101, 111, 112)] == [
        "1 день",
        "3 дня",
        "5 дней",
        "11 дней",
        "12 дней",
        "14 дней",
        "21 день",
        "22 дня",
        "25 дней",
        "101 день",
        "111 дней",
        "112 дней",
    ]
    assert [texts._days(n) for n in (0, 1, 2, 5, 21)] == [
        "сегодня",
        "завтра",
        "через 2 дня",
        "через 5 дней",
        "через 21 день",
    ]
    assert [texts._positions(n) for n in (1, 2, 5, 11, 21)] == [
        "1 позиция",
        "2 позиции",
        "5 позиций",
        "11 позиций",
        "21 позиция",
    ]
    assert [texts._steps(n) for n in (1, 3, 12, 22)] == ["1 шаг", "3 шага", "12 шагов", "22 шага"]

    claim = {
        "kind": "contract",
        "supplier": "С",
        "product": "Сыр",
        "unit": "kg",
        "reference": "500.00",
        "reference_min": "500.00",
        "price": "550.00",
        "since": "2026-09-01",
        "until": "2026-09-30",
        "invoices": [],
        "extra": "500.00",
    }
    for n, words in (
        (1, "в 1 накладной"),
        (3, "в 3 накладных"),
        (21, "в 21 накладной"),
        (166, "в 166 накладных"),
    ):
        for kind in ("contract", "jump"):
            text = texts.supplier_claim({**claim, "kind": kind, "invoices_total": n, "growth_pct": "10.0"})[1]
            assert words in text, (kind, text)
    pieces = {
        "product": "Багет",
        "unit": "pcs",
        "qty": "3",
        "to": "А",
        "from": "Б",
        "by": "2026-10-20",
        "zero_day": "2026-10-20",
        "next_delivery": "2026-10-22",
        "from_stock": "40",
        "from_stock_day": "2026-10-19",
        "from_daily": "2",
        "keep_days": 1,
    }
    text = texts.transfer(pieces)[1]
    assert "нужно 3 шт" in text and "≈ 2 шт в день" in text and "больше чем на 1 день" in text


def test_the_model_writes_the_hqs_notes_only_with_the_facts_numbers(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-35 (CLAUDE.md, p. 1; prompt `agent.v2`): the letter to the supplier by the model may quote 500 ₽,
    540 ₽ — the facts; «верните 600 ₽» is in none of them: refused after one correction, the rules' letter
    stays. The same for a transfer: «6 кг» while the facts say 5."""
    from app.ai import agent_writer
    from app.ai.gateway import FakeModel, Gateway
    from app.tenancy.context import system_context
    from tests.test_agents import _model

    _strict(world.tenant, TODAY)
    (claim,) = [n for n in _notes(owner_engine, "supplier_claim") if n.restaurant_id is None]
    (move,) = _notes(owner_engine, "transfer")
    with get_sessionmaker()() as s:
        ctx = system_context(s, world.tenant)

        def write(model: FakeModel) -> Any:
            return agent_writer.writer(Gateway(model), ctx)

        wrong = FakeModel()
        wrong.replies += [_model("«Сырный дом», просим вернуть 600 ₽ (п. ___).")] * 2
        assert write(wrong)("supplier_claim", claim.facts, claim.text) is None and len(wrong.requests) == 2
        good = "«Сырный дом», по договору (п. ___) цена от 500 ₽ до 540 ₽ за кг; просим вернуть 540 ₽."
        ok = FakeModel()
        ok.replies += [_model(good)]
        assert write(ok)("supplier_claim", claim.facts, claim.text) == (good, 2)
        more = FakeModel()
        more.replies += [_model("Передайте 6 кг пасты из «Сеть А A2» до 20.10.")] * 2
        assert write(more)("transfer", move.facts, move.text) is None


def test_nothing_to_ask_at_the_contract_price_or_of_a_negative_stock(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-29, 30: every invoice of «Сырный дом» at the contract of its day (500 ₽ to 15.09, 540 ₽ after) —
    no claim; A2's books show −2 kg of pasta (a document missing, M7's business) — it gives nothing, and A3's
    count is too old: no transfer. A period with no purchases says «закупок не было»."""
    with Session(owner_engine) as s, s.begin():
        for r in s.execute(select(Receipt).where(Receipt.doc_no.in_(["Н-1", "Н-3"]))).scalars():
            r.amount = r.qty * (500 if r.doc_no == "Н-1" else 540)
        for b in s.execute(select(StockBalance).where(StockBalance.restaurant_id == world.a2)).scalars():
            b.qty = Decimal(-2)
    _strict(world.tenant, TODAY)
    assert [n.key for n in _notes(owner_engine, "supplier_claim")] == ["supplier_claim:M3:A1:P2:jump"]
    assert _notes(owner_engine, "transfer") == []
    period: dict[str, Any] = {"from": "2026-08-01", "to": "2026-08-31", "actual": "5", "theory": "4"}
    period |= {"share": "25", "written_off": "0", "bought": {}, "moved_out": "0", "moved_in": "0"}
    facts: dict[str, Any] = {"product": "Сыр", "unit": "kg", "restaurant": "А", "effect": None}
    facts["network_share"] = "2"
    _, text, items = texts.shortage_story({**facts, "periods": [period], "versions": ["portions"]})
    assert items == [
        "01.08–31.08: по пересчетам 5 кг, по техкартам 4 кг (+25%), списано 0 кг; закупок не было"
    ]
    assert text.startswith("Перерасход, по сети обычно +2%.")


def test_a_rejected_finding_gets_no_story_and_no_transfer(world: World, owner_engine: Engine) -> None:
    """TC-AG-36: a finding the HQ rejected stays open, «hidden from everyone but the review page» — the story
    and the transfer do not build on it; a pending one still does (a shortage cannot wait for the review)."""
    with Session(owner_engine) as s, s.begin():
        for f in s.execute(
            select(Finding).where(Finding.key.in_(["M1:A1:P1", "M6:A1:P2:shortage"]))
        ).scalars():
            f.review_status, f.review_reason = "rejected", "data"
    _strict(world.tenant, TODAY)
    assert _notes(owner_engine, "shortage_story") == []
    assert _notes(owner_engine, "transfer") == []
    with Session(owner_engine) as s, s.begin():
        for f in s.execute(select(Finding).where(Finding.key == "M1:A1:P1")).scalars():
            f.review_status, f.review_reason = "pending", None
    _strict(world.tenant, TODAY)
    assert [n.status for n in _notes(owner_engine, "shortage_story")] == ["new"]
