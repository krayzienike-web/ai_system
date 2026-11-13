"""Agents, stage 11 (ADR 0010): negotiating with a supplier for the network (№ 4), a recipe card the network
overspends (№ 6), following a check (№ 10) — every note to the HQ, the numbers from the code.

Network A, eight weeks of invoices up to 18.10: «Молочный двор» sells cream to A1 at 400 ₽/л, to A2 at 360 and
to A3 at 350 (and a line without a sum, an export defect); eggs at 11, 10 and 10. «Ферма» sells to two
restaurants only. Fries: the network overspends the card by 7,68 % at a 2 % allowance. A check of cream runs
12.10–08.11 (A1 against A2 and A3): A3's sales stop on 15.10, A2 took cream from «Ферма» since 14.10; another
check ended on 16.10."""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents import checks, service, texts
from app.agents.models import AgentNote
from app.catalog.models import MenuItem, Product, RecipeLine, Supplier
from app.core.period import get_today
from app.experiments.models import Experiment
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.main import app
from app.operations.models import Receipt, Sale
from tests.conftest import Network, login

TODAY = date(2026, 10, 20)
LAST = date(2026, 10, 18)  # the network's latest invoice and sale
STAGE_11 = ("supplier_deal", "recipe_update", "check_watch")


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


class World:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        a = network.a
        self.tenant = a.id
        self.a1, self.a2, self.a3 = a.restaurants["A1"], a.restaurants["A2"], a.restaurants["A3"]
        with Session(owner_engine, expire_on_commit=False) as s, s.begin():
            cream = Product(tenant_id=a.id, code="P04", name="Сливки 33%", base_unit="l")
            eggs = Product(tenant_id=a.id, code="P13", name="Яйцо куриное", base_unit="pcs")
            fries = Product(tenant_id=a.id, code="P11", name="Картофель фри", base_unit="kg")
            blank = Product(tenant_id=a.id, code="S01", name="Заготовка фри", base_unit="kg", is_semi=True)
            dairy = Supplier(tenant_id=a.id, code="S3", name="Молочный двор")
            farm = Supplier(tenant_id=a.id, code="S9", name="Ферма")
            dish = MenuItem(tenant_id=a.id, code="M1", name="Картофель фри порция")
            s.add_all([cream, eggs, fries, blank, dairy, farm, dish])
            s.flush()
            self.cream, self.fries, self.blank, self.dairy = cream.id, fries.id, blank.id, dairy.id
            self.dish = dish.id
            batches = {r: _batch(s, a.id, r, "receipts") for r in (self.a1, self.a2, self.a3)}
            sales = {r: _batch(s, a.id, r, "sales") for r in (self.a1, self.a2, self.a3)}

            def receipt(r: UUID, day: date, p: UUID, sup: UUID, qty: str, amount: str) -> None:
                s.add(
                    Receipt(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=batches[r],
                        day=day,
                        doc_no="",
                        supplier_id=sup,
                        product_id=p,
                        qty=Decimal(qty),
                        amount=Decimal(amount),
                    )
                )

            # № 4: cream 400 / 360 / 350 ₽ per litre, 1000 l each in the window; eggs 11 / 10 / 10 ₽.
            for r, cream_sum, egg_sum in (
                (self.a1, "400000", "1100"),
                (self.a2, "360000", "1000"),
                (self.a3, "350000", "1000"),
            ):
                receipt(r, date(2026, 9, 1), cream.id, dairy.id, "1000", cream_sum)
                receipt(r, date(2026, 9, 2), eggs.id, dairy.id, "100", egg_sum)
            receipt(self.a3, LAST, cream.id, dairy.id, "5", "0")  # no sum: left out
            receipt(self.a1, date(2026, 8, 1), cream.id, dairy.id, "1000", "900000")  # before the window
            # «Ферма»: two restaurants only — no median of the network. A2 takes cream from it since 14.10.
            receipt(self.a1, date(2026, 9, 3), eggs.id, farm.id, "100", "5000")
            receipt(self.a2, date(2026, 10, 14), cream.id, farm.id, "10", "3000")

            # № 6: fries at 160 ₽/kg; the dish's card 0.150 kg (0.140 before 2026), the blank's 0.2 kg.
            receipt(self.a1, date(2026, 10, 1), fries.id, dairy.id, "100", "16000")
            s.add_all(
                [
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=dish.id,
                        product_id=fries.id,
                        gross_qty=Decimal("0.140"),
                        valid_from=date(2025, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=dish.id,
                        product_id=fries.id,
                        gross_qty=Decimal("0.150"),
                        valid_from=date(2026, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        semi_product_id=blank.id,
                        product_id=fries.id,
                        gross_qty=Decimal("0.2"),
                        valid_from=date(2026, 1, 1),
                    ),
                ]
            )
            # 560 portions in the eight weeks: 300 a month. Sales of every restaurant up to 18.10 but A3's.
            s.add(
                Sale(
                    tenant_id=a.id,
                    restaurant_id=self.a1,
                    import_batch_id=sales[self.a1],
                    day=date(2026, 10, 1),
                    menu_item_id=dish.id,
                    qty=Decimal(560),
                    revenue=Decimal(100000),
                )
            )
            for r, day in ((self.a1, LAST), (self.a2, LAST), (self.a3, date(2026, 10, 15))):
                s.add(
                    Sale(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=sales[r],
                        day=day,
                        menu_item_id=dish.id,
                        qty=Decimal(0),
                        revenue=Decimal(0),
                    )
                )
            evidence = {
                "product": "P11",
                "allowance": "0.02",
                "median_share": "0.0768",
                "restaurants": {"A1": "0.0781", "A2": "0.0806", "A3": "0.0000"},
            }
            for key, review in (("M1:net:P11", "confirmed"), ("M1:net:P04", "pending")):
                s.add(
                    Finding(
                        tenant_id=a.id,
                        restaurant_id=None,
                        kind="problem",
                        process="accounting",
                        title="Техкарта, вероятно, устарела: Картофель фри",
                        found_on=TODAY,
                        key=key,
                        module="M1",
                        review_status=review,
                        period_from=date(2026, 8, 4),
                        period_to=date(2026, 10, 1),
                        evidence={**evidence, "product": key.rsplit(":", 1)[1]},
                    )
                )

            # № 10: a running check of cream and two finished ones.
            common: dict[str, Any] = {
                "tenant_id": a.id,
                "hypothesis": "…",
                "metric": "…",
                "expected_rub_month": Decimal(1000),
            }
            run = Experiment(
                **common,
                title="Контрольное взвешивание сливок",
                test_restaurant_ids=[self.a1],
                control_restaurant_ids=[self.a2, self.a3],
                starts_on=date(2026, 10, 12),
                ends_on=date(2026, 11, 8),
                status="running",
                metric_product_id=cream.id,
                progress_text="За 7 дн. проверки: разница разниц −0,5 п.п. Судить рано.",
                measured_on=date(2026, 10, 19),
            )
            done = Experiment(
                **common,
                title="Малые партии",
                test_restaurant_ids=[self.a1],
                starts_on=date(2026, 9, 7),
                ends_on=date(2026, 10, 4),
                status="completed",
                verdict="confirmed",
                effect_rub_month=Decimal("1234.50"),
                ci_low_rub_month=Decimal(500),
                ci_high_rub_month=Decimal(2000),
                completed_on=date(2026, 10, 16),
            )
            old = Experiment(
                **common,
                title="Старая проверка",
                test_restaurant_ids=[self.a1],
                starts_on=date(2026, 8, 1),
                ends_on=date(2026, 8, 28),
                status="completed",
                verdict="rejected",
                completed_on=date(2026, 10, 1),
            )
            s.add_all([run, done, old])
            s.flush()
            self.run, self.done = run.id, done.id


@pytest.fixture
def world(network: Network, owner_engine: Engine) -> World:
    return World(network, owner_engine)


def _plain(text: str) -> str:
    """Sums are written with a no-break space between thousands: compared as plain spaces."""
    return text.replace("\u00a0", " ")


def _notes(owner_engine: Engine, agent: str) -> list[AgentNote]:
    with Session(owner_engine) as s:
        return list(
            s.execute(select(AgentNote).where(AgentNote.agent == agent).order_by(AgentNote.key)).scalars()
        )


# ------------------------------------------------------------------ № 4: one price for the network


def test_a_supplier_with_different_prices_gets_a_letter_for_the_network(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-37: eight weeks up to the latest invoice; the median of three restaurants; what the ones above it
    would save a month; a line without a sum and an invoice before the window left out; a product saving
    under 500 ₽ a month counted, not listed; a supplier of two restaurants gets nothing."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "supplier_deal")
    assert (note.audience, note.restaurant_id, note.proposal) == ("hq", None, {"action": "claim"})
    assert note.key == "supplier_deal:S3:2026-10" and note.for_date == LAST
    f = note.facts
    assert (f["since"], f["until"], f["restaurants"]) == ("2026-08-24", "2026-10-18", 3)
    # (400 000 + 360 000 + 350 000 + 3 100 + fries 16 000) × 30 / 56
    assert f["spend_month"] == "604875.00" and f["one_pct_month"] == "6048.75"
    (cream,) = f["products"]
    assert cream == {
        "product": "Сливки 33%",
        "unit": "l",
        "restaurants": 3,
        "above": 1,
        "low": "350.00",
        "median": "360.00",
        "high": "400.00",
        "qty_month": "1607.1",
        "spend_month": "594642.86",
        "saving_month": "21428.57",  # (400 − 360) × 1000 × 30 / 56
    }
    assert f["saving_month"] == "21482.14"  # and the eggs' 53,57
    assert f["products_total"] == 1
    assert note.title == "Переговоры с «Молочный двор»: единая цена для сети"
    assert [_plain(x) for x in note.items] == [
        "Сливки 33%: 1 607,1 л в месяц, 3 ресторана платят от 350,00 ₽ до 400,00 ₽/л, медиана 360,00 ₽ — "
        "цена по медиане сэкономит ≈ 21 429 ₽ в месяц",
        "Для переговоров: единая цена по медиане — ≈ 21 482 ₽ в месяц, каждый процент скидки на весь объем — "
        "≈ 6 049 ₽ в месяц",
    ]
    assert "единую цену не выше 360,00 ₽/л" in note.text and "(п. ___)" in note.text


def test_no_letter_under_the_threshold_and_a_new_one_next_month(world: World, owner_engine: Engine) -> None:
    """TC-AG-38: the prices equal — nothing; dismissed this month, the note comes back with the next month's
    invoices (a new key)."""
    with Session(owner_engine) as s, s.begin():
        for r in s.execute(select(Receipt).where(Receipt.product_id == world.cream)).scalars():
            r.amount = r.qty * 360
    service.run_all(TODAY)
    assert _notes(owner_engine, "supplier_deal") == []


# ------------------------------------------------------------------ № 6: the recipe card


def test_a_card_the_network_overspends_gets_new_quantities(world: World, owner_engine: Engine) -> None:
    """TC-AG-39: the card in force (not the older version) raised by the median less the allowance; the
    portion's cost at the network's price and the month's sales; a semi-product without money; a pending
    finding gives nothing."""
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "recipe_update")
    assert (note.audience, note.restaurant_id, note.key) == ("hq", None, "recipe_update:M1:net:P11")
    f = note.facts
    assert (f["median_pct"], f["allowance_pct"], f["raise_pct"]) == ("7.7", "2", "5.7")
    assert (f["restaurants_over"], f["restaurants"], f["price"]) == (2, 3, "160.00")
    assert f["dishes"] == [
        # 0,150 × 1,0568 = 0,15852 → 0,159; (0,159 − 0,150) × 160 = 1,44 ₽
        {
            "name": "Картофель фри порция",
            "code": "M1",
            "semi": False,
            "old": "0.15",
            "new": "0.159",
            "cost": "1.44",
        },
        {"name": "Заготовка фри", "code": "S01", "semi": True, "old": "0.2", "new": "0.211", "cost": "1.76"},
    ]
    assert f["month_cost"] == "432.00"  # 0,009 kg × 160 ₽ × 300 portions a month
    assert note.items == [
        "Картофель фри порция (блюдо): 0,15 → 0,159 кг, себестоимость порции +1,44 ₽",
        "Заготовка фри (полуфабрикат): 0,2 → 0,211 кг, себестоимость выхода +1,76 ₽",
    ]
    text = _plain(note.text)
    assert "2 из 3 ресторанов" in text and "на 5,7%" in text and "≈ 432 ₽ в месяц" in text


# ------------------------------------------------------------------ № 10: following a check


def test_a_running_check_says_how_far_it_is_and_what_may_spoil_it(world: World, owner_engine: Engine) -> None:
    """TC-AG-40: day 9 of 28, the measurement's own words; A3's sales stop before the network's latest day,
    A2 took cream from a new supplier, 04.11 is a holiday; one note a week; the check to open."""
    service.run_all(TODAY)
    notes = {n.facts["state"]: n for n in _notes(owner_engine, "check_watch")}
    run = notes["running"]
    assert run.key == f"check_watch:{world.run}:2026-10-19" and run.for_date == date(2026, 10, 19)
    assert (run.facts["day"], run.facts["days"], run.proposal) == (9, 28, None)
    assert run.facts["stopped"] == [{"restaurant": "Сеть А A3", "last": "2026-10-15"}]
    assert run.facts["new_suppliers"] == [
        {"restaurant": "Сеть А A2", "supplier": "Ферма", "since": "2026-10-14"}
    ]
    assert run.facts["holidays"] == ["2026-11-04"]
    assert run.title == "Проверка «Контрольное взвешивание сливок»: день 9 из 28"
    assert run.items == [
        "Сеть А A3: продажи выгружены только по 15.10, данные сети — по 18.10",
        "Сеть А A2: с 14.10 товар берут у нового поставщика «Ферма» — цена или фасовка могли измениться",
        "04.11 — праздник: гости и кухня в этот день работают иначе",
    ]
    assert "Судить рано." in run.text and "Что может помешать" in run.text
    # The result of the check that ended on 16.10; the one of 01.10 is old news.
    done = notes["done"]
    assert done.title == "Итог проверки «Малые партии»"
    assert _plain(done.text) == (
        "Проверка «Малые партии» (07.09–04.10) закончилась: эффект подтвержден. Эффект ≈ 1 234 ₽ в месяц "
        "(от 500 ₽ до 2 000 ₽). Что делать дальше, решает УК на экране проверки."
    )
    assert len(notes) == 2


def test_the_holidays_of_a_check() -> None:
    """TC-AG-41: the days off of the Labour Code inside the check's days, the edges included."""
    assert checks.holidays(date(2026, 12, 30), date(2027, 1, 9)) == [date(2027, 1, d) for d in range(1, 9)]
    assert checks.holidays(date(2026, 3, 8), date(2026, 3, 8)) == [date(2026, 3, 8)]
    assert checks.holidays(date(2026, 3, 9), date(2026, 4, 30)) == []


def test_a_quiet_check_and_a_check_without_a_product() -> None:
    """TC-AG-41: nothing in the data — «Помех в данных не видно», no interim measurement yet."""
    _, text, items = texts.by_rules(
        "check_watch",
        {
            "state": "running",
            "title": "Тест",
            "starts_on": "2026-10-12",
            "ends_on": "2026-10-25",
            "day": 3,
            "days": 14,
            "test": ["A1"],
            "control": [],
            "progress": None,
            "data_to": "2026-10-18",
            "stopped": [],
            "new_suppliers": [],
            "holidays": [],
        },
    )
    assert items == []
    assert text == (
        "Проверка идет с 12.10 по 25.10, в проверке — A1. Промежуточного замера еще нет. "
        "Помех в данных не видно."
    )


# ------------------------------------------------------------------ all three


def test_no_director_and_no_other_network_sees_them(
    client: TestClient, world: World, owner_engine: Engine
) -> None:
    """TC-AG-42: all three write to the HQ about the network; the API gives the check to open; «Отправлено»
    of a letter records the decision and sets no task; a director cannot answer them."""
    service.run_all(TODAY)
    r = client.get("/api/agents/notes", headers=login(client, "admin@a.ru"))
    hq = [n for n in r.json() if n["agent"] in STAGE_11]
    assert sorted(n["agent"] for n in hq) == ["check_watch", "check_watch", "recipe_update", "supplier_deal"]
    assert {n["check_id"] for n in hq if n["agent"] == "check_watch"} == {str(world.run), str(world.done)}
    assert all(n["restaurant_id"] is None for n in hq)
    for who in ("director1@a.ru", "admin@b.ru"):
        seen = client.get("/api/agents/notes", headers=login(client, who)).json()
        assert [n for n in seen if n["agent"] in STAGE_11] == []
    deal = next(n for n in hq if n["agent"] == "supplier_deal")
    assert (
        client.post(
            f"/api/agents/notes/{deal['id']}/accept", headers=login(client, "director1@a.ru")
        ).status_code
        == 404
    )
    sent = client.post(f"/api/agents/notes/{deal['id']}/accept", headers=login(client, "admin@a.ru"))
    assert (
        sent.status_code == 200
        and sent.json()["status"] == "accepted"
        and sent.json()["result_task_id"] is None
    )
    watch = next(n for n in hq if n["agent"] == "check_watch")
    nothing = client.post(f"/api/agents/notes/{watch['id']}/accept", headers=login(client, "admin@a.ru"))
    assert nothing.status_code == 422  # nothing to take into work: it can only be hidden


def test_the_run_is_the_same_twice(world: World, owner_engine: Engine) -> None:
    """TC-AG-43 (CLAUDE.md, p. 4): the second run of the day changes nothing."""
    service.run_all(TODAY)
    first = {(n.agent, n.key, n.text) for a in STAGE_11 for n in _notes(owner_engine, a)}
    service.run_all(TODAY)
    assert {(n.agent, n.key, n.text) for a in STAGE_11 for n in _notes(owner_engine, a)} == first


def test_a_check_ends_and_its_weekly_note_expires(world: World, owner_engine: Engine) -> None:
    """TC-AG-43: next week a new note of the running check; the last week's, not decided on, expires."""
    service.run_all(TODAY)
    service.run_all(TODAY + timedelta(days=7))
    by_key = {n.key: n.status for n in _notes(owner_engine, "check_watch")}
    assert by_key[f"check_watch:{world.run}:2026-10-19"] == "expired"
    assert by_key[f"check_watch:{world.run}:2026-10-26"] == "new"
    assert by_key[f"check_watch:{world.done}:done"] == "expired"  # 16.10 + 7 days has passed


def test_a_card_through_a_semi_product_a_changed_card_and_a_removed_product(
    world: World, owner_engine: Engine
) -> None:
    """TC-AG-39 (backend review of stage 11, pp. 2–4): a dish with the product only in its semi-product
    counts in the month through it; a card changed after the finding's period is not raised twice; a dish
    whose newer card has no fries any more is not listed."""
    with Session(owner_engine) as s, s.begin():
        t = world.tenant
        via = MenuItem(tenant_id=t, code="M2", name="Фри из заготовки")
        burger = MenuItem(tenant_id=t, code="M3", name="Бургер")
        salad = MenuItem(tenant_id=t, code="M4", name="Салат")
        s.add_all([via, burger, salad])
        s.flush()
        lines = [
            (via.id, world.blank, "0.5", date(2026, 1, 1)),  # 0,1 kg of fries a portion, through the blank
            (burger.id, world.fries, "0.2", date(2026, 10, 10)),  # changed after the period (01.10)
            (salad.id, world.fries, "0.05", date(2026, 1, 1)),
            (salad.id, world.cream, "0.05", date(2026, 2, 1)),  # the newer card has no fries
        ]
        for parent, product, qty, since in lines:
            s.add(
                RecipeLine(
                    tenant_id=t,
                    menu_item_id=parent,
                    product_id=product,
                    gross_qty=Decimal(qty),
                    valid_from=since,
                )
            )
        batch = (
            s.execute(select(Sale.import_batch_id).where(Sale.restaurant_id == world.a1)).scalars().first()
        )
        s.add(
            Sale(
                tenant_id=t,
                restaurant_id=world.a1,
                import_batch_id=batch,
                day=date(2026, 10, 2),
                menu_item_id=via.id,
                qty=Decimal(56),
                revenue=Decimal(0),
            )
        )
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "recipe_update")
    assert [d["name"] for d in note.facts["dishes"]] == ["Картофель фри порция", "Заготовка фри"]
    assert note.facts["changed"] == ["Бургер"]
    # + 0,5 × 0,011 kg × 160 ₽ × 30 portions a month = 26,40 ₽
    assert note.facts["month_cost"] == "458.40"
    assert note.items[-1] == "Уже изменены после этого периода, их не трогаем: Бургер"


def test_a_card_without_a_price_says_no_sum(world: World, owner_engine: Engine) -> None:
    """TC-AG-39 (review, p. 4): no invoices of the product in the window — the quantities, no money."""
    with Session(owner_engine) as s, s.begin():
        for r in s.execute(select(Receipt).where(Receipt.product_id == world.fries)).scalars():
            s.delete(r)
    service.run_all(TODAY)
    (note,) = _notes(owner_engine, "recipe_update")
    assert note.facts["month_cost"] is None and note.facts["price"] is None
    assert [d["cost"] for d in note.facts["dishes"]] == [None, None]
    assert "Себестоимость продаж" not in note.text
    assert note.items[0] == "Картофель фри порция (блюдо): 0,15 → 0,159 кг"


def test_many_small_savings_give_no_letter_and_break_nothing(world: World, owner_engine: Engine) -> None:
    """TC-AG-38 (review, p. 1): seven products of a supplier each saving 460 ₽ a month — 3 225 ₽ together,
    but none to name: no letter, and the morning run of the network goes on (the other agents' notes)."""
    with Session(owner_engine) as s, s.begin():
        t = world.tenant
        small = Supplier(tenant_id=t, code="S7", name="Мелочи")
        s.add(small)
        s.flush()
        batch = {
            r: s.execute(select(Receipt.import_batch_id).where(Receipt.restaurant_id == r)).scalars().first()
            for r in (world.a1, world.a2, world.a3)
        }
        for n in range(7):
            p = Product(tenant_id=t, code=f"X{n}", name=f"Мелочь {n}", base_unit="pcs")
            s.add(p)
            s.flush()
            for r, amount in ((world.a1, "1860"), (world.a2, "1000"), (world.a3, "1000")):
                s.add(
                    Receipt(
                        tenant_id=t,
                        restaurant_id=r,
                        import_batch_id=batch[r],
                        day=date(2026, 9, 10),
                        doc_no="",
                        supplier_id=small.id,
                        product_id=p.id,
                        qty=Decimal(100),
                        amount=Decimal(amount),
                    )
                )
    service.run_all(TODAY)
    assert [n.facts["supplier"] for n in _notes(owner_engine, "supplier_deal")] == ["Молочный двор"]
    assert len(_notes(owner_engine, "recipe_update")) == 1


def test_a_day_behind_is_not_a_stopped_export(world: World, owner_engine: Engine) -> None:
    """TC-AG-40 (review, p. 5): A2's sales a day behind the network are usual; A3, three days behind, is
    listed."""
    with Session(owner_engine) as s, s.begin():
        for sale in s.execute(select(Sale).where(Sale.restaurant_id == world.a2, Sale.day == LAST)).scalars():
            sale.day = LAST - timedelta(days=1)
    service.run_all(TODAY)
    run = next(n for n in _notes(owner_engine, "check_watch") if n.facts["state"] == "running")
    assert [x["restaurant"] for x in run.facts["stopped"]] == ["Сеть А A3"]
