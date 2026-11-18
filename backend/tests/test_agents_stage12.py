"""Agents, stage 12 (ADR 0010): the result of a stock count (№ 13) and menu prices after purchases grew (№
14).
Counts. Network A counts on 01.06, 01.08 and 01.10 (A1), 01.08 and 01.10 (A2), 01.06 and 01.09 (A3: too long
ago). Cheese at 500 ₽/kg, 0.1 kg in a pizza, 1500 pizzas a period, a 2 % allowance:
- A1, 01.08–01.10: 10 kg + 200 bought − 5 handed to A2 − 20 left = 185 used against 150 by the cards, nothing
  written off — 35 kg unexplained, 32 beyond the allowance: 16 000 ₽, 7 869 ₽ a month (61 days). The period
  before: 10 kg unexplained, 7 beyond — 3 500 ₽, 1 721 ₽ a month. Fries: 50 kg over 150 — the network's card.
- A2: 10 + 150 + 5 received − 14 = 151 used against 150: within the allowance.

Menu. Salmon cost the network 1 000 ₽/kg in 22.06–19.07 and 1 600 ₽/kg in 21.09–18.10 (the M2 windows).
«Лосось гриль» (1 000 ₽, 0.2 kg) goes from 20 % to 32 % at a 30 % target; «Паста» (0.1 kg) stays at 16 %;
«Тартар» (500 ₽, 0.2 kg) was at 40 % already; «Боул» got a new card on 10.10: 0.1 → 0.2 kg."""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents import service, texts
from app.agents.models import AgentNote
from app.catalog.models import MenuItem, Product, RecipeLine
from app.core.period import get_today
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.main import app
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tasks.models import Task
from tests.conftest import Network, hq_task, login

TODAY = date(2026, 10, 20)


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


def _plain(text: str) -> str:
    return text.replace(" ", " ")


def _notes(owner_engine: Engine, agent: str) -> list[AgentNote]:
    with Session(owner_engine) as s:
        return list(
            s.execute(select(AgentNote).where(AgentNote.agent == agent).order_by(AgentNote.key)).scalars()
        )


class Counts:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        a = network.a
        self.tenant = a.id
        self.a1, self.a2, self.a3 = a.restaurants["A1"], a.restaurants["A2"], a.restaurants["A3"]
        with Session(owner_engine, expire_on_commit=False) as s, s.begin():
            cheese = Product(tenant_id=a.id, code="P01", name="Сыр", base_unit="kg")
            fries = Product(tenant_id=a.id, code="P11", name="Картофель фри", base_unit="kg")
            pizza = MenuItem(tenant_id=a.id, code="M1", name="Пицца")
            chips = MenuItem(tenant_id=a.id, code="M8", name="Фри")
            s.add_all([cheese, fries, pizza, chips])
            s.flush()
            self.cheese, self.fries = cheese.id, fries.id
            s.add_all(
                [
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=pizza.id,
                        product_id=cheese.id,
                        gross_qty=Decimal("0.1"),
                        valid_from=date(2025, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=chips.id,
                        product_id=fries.id,
                        gross_qty=Decimal("0.15"),
                        valid_from=date(2025, 1, 1),
                    ),
                ]
            )
            self.batch = {r: _batch(s, a.id, r, "any") for r in (self.a1, self.a2, self.a3)}

            def count(r: UUID, day: date, p: UUID, actual: str) -> None:
                s.add(
                    InventoryCount(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=self.batch[r],
                        day=day,
                        product_id=p,
                        book_qty=None,
                        actual_qty=Decimal(actual),
                    )
                )

            def receipt(r: UUID, day: date, p: UUID, qty: str, amount: str) -> None:
                s.add(
                    Receipt(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=self.batch[r],
                        day=day,
                        doc_no="",
                        product_id=p,
                        qty=Decimal(qty),
                        amount=Decimal(amount),
                    )
                )

            def sale(r: UUID, day: date, item: UUID, qty: int) -> None:
                s.add(
                    Sale(
                        tenant_id=a.id,
                        restaurant_id=r,
                        import_batch_id=self.batch[r],
                        day=day,
                        menu_item_id=item,
                        qty=Decimal(qty),
                        revenue=Decimal(qty * 500),
                    )
                )

            # A1
            for day, actual in (
                (date(2026, 6, 1), "10"),
                (date(2026, 8, 1), "10"),
                (date(2026, 10, 1), "20"),
            ):
                count(self.a1, day, cheese.id, actual)
                count(self.a1, day, fries.id, "0")
            receipt(self.a1, date(2026, 7, 1), cheese.id, "160", "80000")
            receipt(self.a1, date(2026, 9, 1), cheese.id, "200", "100000")
            receipt(self.a1, date(2026, 9, 1), fries.id, "200", "32000")
            sale(self.a1, date(2026, 7, 10), pizza.id, 1500)
            sale(self.a1, date(2026, 9, 10), pizza.id, 1500)
            sale(self.a1, date(2026, 9, 10), chips.id, 1000)
            s.add(
                Transfer(
                    tenant_id=a.id,
                    restaurant_id=self.a1,
                    to_restaurant_id=self.a2,
                    import_batch_id=self.batch[self.a1],
                    day=date(2026, 9, 5),
                    product_id=cheese.id,
                    qty=Decimal(5),
                )
            )
            # A2: within the allowance
            count(self.a2, date(2026, 8, 1), cheese.id, "10")
            count(self.a2, date(2026, 10, 1), cheese.id, "14")
            receipt(self.a2, date(2026, 9, 1), cheese.id, "150", "75000")
            sale(self.a2, date(2026, 9, 10), pizza.id, 1500)
            # A3: the last count is seven weeks old
            count(self.a3, date(2026, 6, 1), cheese.id, "10")
            count(self.a3, date(2026, 9, 1), cheese.id, "0")
            receipt(self.a3, date(2026, 7, 1), cheese.id, "500", "250000")
            sale(self.a3, date(2026, 7, 10), pizza.id, 1000)

            # The network's card of fries (checked) and A1's finding about cheese with a task (ADR 0009).
            s.add(
                Finding(
                    tenant_id=a.id,
                    restaurant_id=None,
                    kind="problem",
                    process="accounting",
                    title="Техкарта, вероятно, устарела: Картофель фри",
                    found_on=TODAY,
                    key="M1:net:P11",
                    module="M1",
                    review_status="confirmed",
                    evidence={"product": "P11", "allowance": "0.02", "median_share": "0.3"},
                )
            )
            mine = Finding(
                tenant_id=a.id,
                restaurant_id=self.a1,
                kind="problem",
                process="accounting",
                title="Перерасход по техкарте: Сыр",
                found_on=TODAY,
                key="M1:A1:P01",
                module="M1",
                review_status="confirmed",
                evidence={"product": "P01"},
            )
            s.add(mine)
            s.flush()
            self.finding = mine.id


@pytest.fixture
def counts(network: Network, owner_engine: Engine) -> Counts:
    return Counts(network, owner_engine)


# ------------------------------------------------------------------ № 13: the result of a count


def test_a_count_gives_the_director_what_to_explain(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-51: U = A − T − W beyond the category's allowance, at the restaurant's price; the hints; the
    network's card named apart and not counted; a restaurant within the allowance or counted long ago — no
    note."""
    hq_task(owner_engine, counts.finding)
    service.run_all(TODAY)
    notes = _notes(owner_engine, "count_result")
    (mine,) = [n for n in notes if n.audience == "director"]
    assert (mine.restaurant_id, mine.key, mine.for_date) == (
        counts.a1,
        "count_result:A1:2026-10-01",
        date(2026, 10, 1),
    )
    (cheese,) = mine.facts["products"]
    assert (cheese["qty"], cheese["rub"]) == ("32", "16000")
    assert cheese["hints"] == [
        {"kind": "finding", "finding": "Перерасход по техкарте: Сыр"},
        {"kind": "no_write_offs"},
        {"kind": "transfers_out", "qty": "5"},
    ]
    assert mine.facts["card_products"] == ["Картофель фри"]
    proposal = mine.proposal or {}
    assert (proposal["action"], proposal["due_on"], proposal["title"]) == (
        "create_task",
        "2026-10-22",
        "Объяснить расхождения инвентаризации 01.10",
    )
    # The sum as on the card, thousands apart (frontend review of stage 12, p. 2)
    assert [_plain(x) for x in proposal["checklist"]] == ["Объяснить: Сыр — 16 000 ₽ сверх допуска"]
    assert _plain(mine.items[0]) == (
        "Сыр: 32 кг сверх допуска ≈ 16 000 ₽. С чего начать: по нему уже открыта находка «Перерасход по "
        "техкарте: Сыр»; оформлены ли списания: за период их нет; дошли ли до получателя перемещения: "
        "ушло 5 кг"
    )
    assert "Картофель фри: расход выше техкарты во всей сети" in mine.items[1]


def test_the_hq_gets_where_differences_grew(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-52: one note about the network: a month now against the count before; grown first; within the
    allowance — a number only."""
    service.run_all(TODAY)
    (net,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "hq"]
    assert (net.restaurant_id, net.key, net.proposal) == (None, "count_result:net:2026-10-01", None)
    assert net.facts["counted"] == 2 and net.facts["within"] == 1 and net.facts["grew"] == 1
    (a1,) = net.facts["restaurants"]
    assert (a1["code"], a1["month"], a1["before"], a1["grew"], a1["top"], a1["top_rub"]) == (
        "A1",
        "7869",
        "1721",
        True,
        "Сыр",
        "16000",
    )
    assert net.title == "Итоги инвентаризаций: расхождения заметно выросли в 1 из 1"


def test_a_finding_without_a_task_is_no_hint(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-52, ADR 0009: the director does not see a finding without a task — the note does not name it."""
    service.run_all(TODAY)
    (mine,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "director"]
    assert [h["kind"] for h in mine.facts["products"][0]["hints"]] == ["no_write_offs", "transfers_out"]


def test_written_off_products_and_an_old_count(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-53: write-offs explain a part and drop the hint; three weeks after the count the notes expire."""
    with Session(owner_engine) as s, s.begin():
        s.add(
            WriteOff(
                tenant_id=counts.tenant,
                restaurant_id=counts.a1,
                import_batch_id=counts.batch[counts.a1],
                day=date(2026, 9, 20),
                product_id=counts.cheese,
                qty=Decimal(10),
            )
        )
    service.run_all(TODAY)
    (mine,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "director"]
    cheese = mine.facts["products"][0]
    assert (cheese["qty"], cheese["rub"]) == ("22", "11000")
    assert "no_write_offs" not in [h["kind"] for h in cheese["hints"]]
    service.run_all(date(2026, 10, 23))  # 22 days after the count
    assert {n.status for n in _notes(owner_engine, "count_result")} == {"expired"}


def test_the_count_result_through_the_api(client: TestClient, counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-54: the director of A1 sees their result and makes the task; the other directors and the other
    network see nothing; the HQ's list has its summary only, a restaurant's list — the director's note too."""
    service.run_all(TODAY)
    mine = [
        n
        for n in client.get("/api/agents/notes", headers=login(client, "director1@a.ru")).json()
        if n["agent"] == "count_result"
    ]
    assert [(n["audience"], n["restaurant_id"]) for n in mine] == [("director", str(counts.a1))]
    for who in ("director2@a.ru", "director3@a.ru", "admin@b.ru"):
        seen = client.get("/api/agents/notes", headers=login(client, who)).json()
        assert [n for n in seen if n["agent"] == "count_result"] == []
    admin = login(client, "admin@a.ru")
    hq = [n for n in client.get("/api/agents/notes", headers=admin).json() if n["agent"] == "count_result"]
    assert [n["audience"] for n in hq] == ["hq"]
    one = client.get("/api/agents/notes", params={"restaurant": str(counts.a1)}, headers=admin).json()
    assert [n["audience"] for n in one if n["agent"] == "count_result"] == ["director"]
    assert client.post(f"/api/agents/notes/{hq[0]['id']}/accept", headers=admin).status_code == 422
    done = client.post(f"/api/agents/notes/{mine[0]['id']}/accept", headers=login(client, "director1@a.ru"))
    assert done.status_code == 200 and done.json()["status"] == "accepted"
    with Session(owner_engine) as s:
        task = s.get(Task, UUID(done.json()["result_task_id"]))
        assert task is not None
        assert (task.title, task.due_on, [_plain(x) for x in task.checklist], task.restaurant_id) == (
            "Объяснить расхождения инвентаризации 01.10",
            date(2026, 10, 22),
            ["Объяснить: Сыр — 16 000 ₽ сверх допуска"],
            counts.a1,
        )


def test_the_count_result_is_the_same_twice(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-55 (CLAUDE.md, p. 4): the second run of the day changes nothing."""
    service.run_all(TODAY)
    first = {(n.key, n.text, tuple(n.items)) for n in _notes(owner_engine, "count_result")}
    service.run_all(TODAY)
    assert {(n.key, n.text, tuple(n.items)) for n in _notes(owner_engine, "count_result")} == first


def _count(
    owner_engine: Engine, c: Counts, day: date, product: UUID, actual: str, r: UUID | None = None
) -> None:
    with Session(owner_engine) as s, s.begin():
        where = r or c.a1
        s.add(
            InventoryCount(
                tenant_id=c.tenant,
                restaurant_id=where,
                import_batch_id=c.batch[where],
                day=day,
                product_id=product,
                book_qty=None,
                actual_qty=Decimal(actual),
            )
        )


def test_a_short_recount_neither_hides_the_result_nor_counts_as_within(
    counts: Counts, owner_engine: Engine
) -> None:
    """TC-AG-61 (backend review of stage 12, p. 1): a recount three days after the count is too short to judge
    — the director keeps the result of 01.10, the HQ's summary still has A1 with its numbers."""
    for p, actual in ((counts.cheese, "20"), (counts.fries, "0")):
        _count(owner_engine, counts, date(2026, 10, 4), p, actual)
    service.run_all(TODAY)
    notes = [n for n in _notes(owner_engine, "count_result") if n.status == "new"]
    assert sorted(n.key for n in notes) == ["count_result:A1:2026-10-01", "count_result:net:2026-10-01"]
    (net,) = [n for n in notes if n.audience == "hq"]
    assert [(x["code"], x["month"], x["before"]) for x in net.facts["restaurants"]] == [
        ("A1", "7869", "1721")
    ]


def test_the_summary_says_what_the_director_got(counts: Counts, owner_engine: Engine) -> None:
    """TC-AG-61 (review, p. 2): the HQ's line says how many products the director has to explain."""
    service.run_all(TODAY)
    (net,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "hq"]
    assert net.facts["restaurants"][0]["director"] == 1 and net.facts["least"] == "3000"
    assert _plain(net.items[0]).endswith("директору — 1 товар к объяснению")
    _title, _text, items = texts.by_rules(
        "count_result",
        {**net.facts, "restaurants": [{**net.facts["restaurants"][0], "director": 0}]},
    )
    assert _plain(items[0]).endswith("директору объяснять нечего: каждый товар меньше 3 000 ₽ в месяц")


def test_a_product_received_only_by_transfer_is_priced_by_the_network(
    counts: Counts, owner_engine: Engine
) -> None:
    """TC-AG-62 (review, p. 5): A1 bought no sauce, only got 50 kg from A2 (300 ₽/kg there): 20 kg by the
    cards, nothing left — 29,6 kg beyond the allowance at the network's price, marked as such."""
    with Session(owner_engine) as s, s.begin():
        sauce = Product(tenant_id=counts.tenant, code="P20", name="Соус", base_unit="kg")
        pasta = MenuItem(tenant_id=counts.tenant, code="M20", name="Паста")
        s.add_all([sauce, pasta])
        s.flush()
        s.add(
            RecipeLine(
                tenant_id=counts.tenant,
                menu_item_id=pasta.id,
                product_id=sauce.id,
                gross_qty=Decimal("0.1"),
                valid_from=date(2025, 1, 1),
            )
        )
        s.add(
            Receipt(
                tenant_id=counts.tenant,
                restaurant_id=counts.a2,
                import_batch_id=counts.batch[counts.a2],
                day=date(2026, 9, 1),
                doc_no="",
                product_id=sauce.id,
                qty=Decimal(100),
                amount=Decimal(30000),
            )
        )
        s.add(
            Transfer(
                tenant_id=counts.tenant,
                restaurant_id=counts.a2,
                to_restaurant_id=counts.a1,
                import_batch_id=counts.batch[counts.a2],
                day=date(2026, 9, 2),
                product_id=sauce.id,
                qty=Decimal(50),
            )
        )
        s.add(
            Sale(
                tenant_id=counts.tenant,
                restaurant_id=counts.a1,
                import_batch_id=counts.batch[counts.a1],
                day=date(2026, 9, 10),
                menu_item_id=pasta.id,
                qty=Decimal(200),
                revenue=Decimal(1),
            )
        )
        sauce_id = sauce.id
    for day in (date(2026, 8, 1), date(2026, 10, 1)):
        _count(owner_engine, counts, day, sauce_id, "0")
    service.run_all(TODAY)
    (mine,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "director"]
    sauce_line = next(p for p in mine.facts["products"] if p["name"] == "Соус")
    assert (sauce_line["qty"], sauce_line["rub"], sauce_line["network_price"]) == ("29.6", "8880", True)
    assert "по средней цене сети" in next(i for i in mine.items if i.startswith("Соус"))


def test_a_late_answer_names_the_explanation(
    client: TestClient, counts: Counts, owner_engine: Engine
) -> None:
    """TC-AG-54 (review, p. 9): «Создать задачу» after the note's last day says the explanation's deadline
    passed, not the count's day."""
    service.run_all(TODAY)
    (mine,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "director"]
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 23)
    r = client.post(f"/api/agents/notes/{mine.id}/accept", headers=login(client, "director1@a.ru"))
    assert r.status_code == 422 and "Срок объяснения уже прошел" in r.text


# ------------------------------------------------------------------ № 14: menu prices


class Menu:
    def __init__(self, network: Network, owner_engine: Engine) -> None:
        a = network.a
        self.tenant = a.id
        a1 = a.restaurants["A1"]
        with Session(owner_engine, expire_on_commit=False) as s, s.begin():
            salmon = Product(tenant_id=a.id, code="P09", name="Лосось", base_unit="kg", category="Рыба")
            s.add(salmon)
            dishes = {
                code: MenuItem(tenant_id=a.id, code=code, name=name, category="Горячее", price=Decimal(price))
                for code, name, price in (
                    ("G", "Лосось гриль", 1000),
                    ("P", "Паста", 1000),
                    ("T", "Тартар", 500),
                    ("B", "Боул", 1000),
                )
            }
            s.add_all(dishes.values())
            s.flush()
            for code, qty, since in (
                ("G", "0.2", date(2025, 1, 1)),
                ("P", "0.1", date(2025, 1, 1)),
                ("T", "0.2", date(2025, 1, 1)),
                ("B", "0.1", date(2025, 1, 1)),
                ("B", "0.2", date(2026, 10, 10)),
            ):
                s.add(
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=dishes[code].id,
                        product_id=salmon.id,
                        gross_qty=Decimal(qty),
                        valid_from=since,
                    )
                )
            batch = _batch(s, a.id, a1, "any")
            for day, qty, amount in (
                (date(2026, 6, 30), "100", "100000"),
                (date(2026, 10, 18), "100", "160000"),
            ):
                s.add(
                    Receipt(
                        tenant_id=a.id,
                        restaurant_id=a1,
                        import_batch_id=batch,
                        day=day,
                        doc_no="",
                        product_id=salmon.id,
                        qty=Decimal(qty),
                        amount=Decimal(amount),
                    )
                )
            for code, portions in (("G", 280), ("P", 100), ("T", 50), ("B", 100)):
                s.add(
                    Sale(
                        tenant_id=a.id,
                        restaurant_id=a1,
                        import_batch_id=batch,
                        day=date(2026, 10, 5),
                        menu_item_id=dishes[code].id,
                        qty=Decimal(portions),
                        revenue=Decimal(portions) * (dishes[code].price or 0),
                    )
                )
            growth = Finding(
                tenant_id=a.id,
                restaurant_id=None,
                kind="problem",
                process="purchasing",
                title="Цена выросла по всей сети: Лосось",
                found_on=TODAY,
                key="M3:net:P09:growth",
                module="M3",
                review_status="confirmed",
                evidence={"product": "P09", "kind": "growth"},
            )
            s.add(growth)
            # Review of stage 12, p. 6: a dish without a menu price — priced by the till, as M2 does.
            chef = MenuItem(tenant_id=a.id, code="C", name="Лосось шеф", category="Горячее")
            # P. 8: a soup whose sauce (a semi-product) got a new card on 12.10: cream 0.1 → 1 l per kg.
            cream = Product(tenant_id=a.id, code="P04", name="Сливки", base_unit="l")
            sauce = Product(tenant_id=a.id, code="S1", name="Соус", base_unit="kg", is_semi=True)
            soup = MenuItem(tenant_id=a.id, code="S", name="Суп", category="Супы", price=Decimal(50))
            s.add_all([chef, cream, sauce, soup])
            s.flush()
            s.add_all(
                [
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=chef.id,
                        product_id=salmon.id,
                        gross_qty=Decimal("0.2"),
                        valid_from=date(2025, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        menu_item_id=soup.id,
                        product_id=sauce.id,
                        gross_qty=Decimal("0.2"),
                        valid_from=date(2025, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        semi_product_id=sauce.id,
                        product_id=cream.id,
                        gross_qty=Decimal("0.1"),
                        valid_from=date(2025, 1, 1),
                    ),
                    RecipeLine(
                        tenant_id=a.id,
                        semi_product_id=sauce.id,
                        product_id=cream.id,
                        gross_qty=Decimal("1"),
                        valid_from=date(2026, 10, 12),
                    ),
                ]
            )
            for day in (date(2026, 6, 30), date(2026, 10, 18)):
                s.add(
                    Receipt(
                        tenant_id=a.id,
                        restaurant_id=a1,
                        import_batch_id=batch,
                        day=day,
                        doc_no="",
                        product_id=cream.id,
                        qty=Decimal(10),
                        amount=Decimal(1000),
                    )
                )
            for item, sold, revenue in ((chef.id, 28, 28000), (soup.id, 28, 1400)):
                s.add(
                    Sale(
                        tenant_id=a.id,
                        restaurant_id=a1,
                        import_batch_id=batch,
                        day=date(2026, 10, 5),
                        menu_item_id=item,
                        qty=Decimal(sold),
                        revenue=Decimal(revenue),
                    )
                )
            s.flush()
            self.growth = growth.id


@pytest.fixture
def menu(network: Network, owner_engine: Engine) -> Menu:
    return Menu(network, owner_engine)


def test_a_price_rise_lists_the_dishes_pushed_above_the_target(menu: Menu, owner_engine: Engine) -> None:
    """TC-AG-56: the M2 windows and prices; only dishes that were within the target; the price rounded up to
    10 ₽, a portion cut by at most a quarter (down to 0.001); the margin lost a month; «already above»
    counted."""
    service.run_all(TODAY)
    notes = {n.key: n for n in _notes(owner_engine, "menu_price")}
    price = notes["menu_price:M3:net:P09:growth"]
    assert (price.audience, price.restaurant_id, price.proposal) == ("hq", None, {"action": "claim"})
    f = price.facts
    assert (f["price"], f["price_before"], f["growth_pct"], f["already"]) == ("1600.00", "1000.00", "60.0", 1)
    assert [d["name"] for d in f["dishes"]] == ["Боул", "Лосось гриль", "Лосось шеф"]
    assert f["dishes"][2]["price"] == "1000.00"  # 28 000 ₽ for 28 portions (review of stage 12, p. 6)
    grill = f["dishes"][1]
    assert grill == {
        "name": "Лосось гриль",
        "code": "G",
        "price": "1000.00",
        "cost": "320.00",
        "cost_before": "200.00",
        "food_cost_pct": "32.0",
        "food_cost_before_pct": "20.0",
        "target_pct": "30.0",
        "new_price": "1070.00",
        "cut": {"old": "0.200", "new": "0.187"},
        "lost_month": "36000.00",
    }
    assert f["dishes"][0]["lost_month"] == "23571.43"  # 220 ₽ more (card and price) × 107,1 portions
    assert _plain(price.items[1]) == (
        "Лосось гриль: себестоимость 200,00 ₽ → 320,00 ₽, фудкост 20,0% → 32,0% при цели 30,0%. Цена 1 070 ₽ "
        "вместо 1 000 ₽ или лосось в порции 0,200 → 0,187 кг; маржа сейчас теряет ≈ 36 000 ₽ в месяц"
    )
    assert price.title == "Цены меню: «Лосось» +60,0% к цене закупки"  # no gender to agree (review, p. 9)


def test_a_new_card_is_a_reason_too(menu: Menu, owner_engine: Engine) -> None:
    """TC-AG-57: a card that started within 28 days of the window's end — the dish's own or its
    semi-product's (review of stage 12, p. 8); no portion to cut is proposed; a dish already in the note about
    a price is not repeated in the note about cards (p. 10)."""
    service.run_all(TODAY)
    notes = {n.key: n for n in _notes(owner_engine, "menu_price")}
    assert "menu_price:card:2026-10-10" not in notes  # «Боул» is in the salmon's note
    card = notes["menu_price:card:2026-10-12"]
    assert card.facts["reason"] == "card" and card.for_date == date(2026, 10, 12)
    assert [(d["name"], d["cut"], d["cost_before"], d["cost"]) for d in card.facts["dishes"]] == [
        ("Суп", None, "2.00", "20.00")
    ]
    assert card.title == "Цены меню: новые техкарты с 12.10"
    with Session(owner_engine) as s, s.begin():
        f = s.get(Finding, menu.growth)
        assert f is not None
        f.review_status = "pending"
    service.run_all(TODAY)
    alone = {n.key: n for n in _notes(owner_engine, "menu_price") if n.status == "new"}
    assert [d["name"] for d in alone["menu_price:card:2026-10-10"].facts["dishes"]] == ["Боул"]


def test_no_note_without_a_checked_open_rise(menu: Menu, owner_engine: Engine) -> None:
    """TC-AG-58: a rise waiting for the check, or closed, gives no note (the new card still does)."""
    for review, status in (("pending", "new"), ("confirmed", "resolved")):
        with Session(owner_engine) as s, s.begin():
            f = s.get(Finding, menu.growth)
            assert f is not None
            f.review_status, f.status = review, status
        service.run_all(TODAY)
        assert [n.key for n in _notes(owner_engine, "menu_price") if n.status == "new"] == [
            "menu_price:card:2026-10-10",
            "menu_price:card:2026-10-12",
        ]


def test_menu_prices_are_the_hqs_only(client: TestClient, menu: Menu, owner_engine: Engine) -> None:
    """TC-AG-59: no director and no other network sees them; «Отправлено» records the decision, no task."""
    service.run_all(TODAY)
    for who in ("director1@a.ru", "admin@b.ru"):
        seen = client.get("/api/agents/notes", headers=login(client, who)).json()
        assert [n for n in seen if n["agent"] == "menu_price"] == []
    admin = login(client, "admin@a.ru")
    hq = [n for n in client.get("/api/agents/notes", headers=admin).json() if n["agent"] == "menu_price"]
    assert len(hq) == 2  # the salmon and the soup's sauce
    assert (
        client.post(
            f"/api/agents/notes/{hq[0]['id']}/accept", headers=login(client, "director1@a.ru")
        ).status_code
        == 404
    )
    sent = client.post(f"/api/agents/notes/{hq[0]['id']}/accept", headers=admin)
    assert sent.json()["status"] == "accepted" and sent.json()["result_task_id"] is None


def test_the_rules_texts_of_menu_prices() -> None:
    """TC-AG-56: «already above» line; a dish without a portion to cut."""
    title, text, items = texts.by_rules(
        "menu_price",
        {
            "reason": "card",
            "since": "2026-10-10",
            "already": 2,
            "dishes": [
                {
                    "name": "Боул",
                    "price": "1000.00",
                    "cost": "320.00",
                    "cost_before": "100.00",
                    "food_cost_pct": "32.0",
                    "food_cost_before_pct": "10.0",
                    "target_pct": "30.0",
                    "new_price": "1070.00",
                    "cut": None,
                    "lost_month": "100.00",
                }
            ],
        },
    )
    assert title == "Цены меню: новые техкарты с 10.10"
    assert _plain(text).startswith("С 10.10 действуют новые техкарты, и фудкост 1 блюда ушел выше цели")
    assert " или " not in items[0]
    # Not every such dish has a finding (M2's threshold): the line promises none (review of stage 12, p. 7)
    assert items[1] == "Еще блюд выше цели и до этого: 2"


def test_a_menu_without_purchases_says_nothing(network: Network, owner_engine: Engine) -> None:
    """TC-AG-58: no invoices — no window, no note."""
    service.run_all(TODAY + timedelta(days=1))
    assert _notes(owner_engine, "menu_price") == []
