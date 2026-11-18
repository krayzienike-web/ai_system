"""Agents of stage 12, the edges (test engineer, end of stage 12): what the plan (docs/06 «Этап 12») and ADR
0010 say about the count's result (№ 13) and menu prices (№ 14) beyond the main scenario of
`test_agents_stage12.py`, on the same data (its docstring has the numbers).

Reminder of A1's period 01.08–01.10 (61 days): cheese 10 kg + 200 bought − 5 handed to A2 − 20 left = 185 used
against 150 by the cards; fries — 200 bought at 160 ₽/kg, 150 by the cards, the network's card."""

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.agents import counts as count_agent
from app.agents import service, texts
from app.agents.models import AgentNote
from app.ai import agent_writer
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, text_reply
from app.catalog.models import MenuItem, Product, RecipeLine
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.insights.models import Finding
from app.main import app
from app.norms.models import NormSettings
from app.operations.models import InventoryCount, Receipt, Sale
from app.tenancy.context import system_context
from app.tenancy.models import Restaurant
from tests.conftest import Network, login
from tests.test_agents_stage12 import TODAY, Counts, Menu, _batch, _count, _notes, _plain

# The fixtures of the main file, shared here (pytest finds them by name in the module).
from tests.test_agents_stage12 import counts as counts
from tests.test_agents_stage12 import menu as menu


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _actual(owner_engine: Engine, restaurant: Any, day: date, product: Any, actual: str) -> None:
    with Session(owner_engine) as s, s.begin():
        s.execute(
            update(InventoryCount)
            .where(
                InventoryCount.restaurant_id == restaurant,
                InventoryCount.day == day,
                InventoryCount.product_id == product,
            )
            .values(actual_qty=Decimal(actual))
        )


def _norms(owner_engine: Engine, tenant: Any, **values: Any) -> None:
    with Session(owner_engine) as s, s.begin():
        row = s.execute(select(NormSettings).where(NormSettings.tenant_id == tenant)).scalar_one_or_none()
        if row is None:
            row = NormSettings(
                tenant_id=tenant, food_cost_target_pct=Decimal(30), loss_default_pct=Decimal(2)
            )
            s.add(row)
        for k, v in values.items():
            setattr(row, k, v)


def _a2_beyond(owner_engine: Engine, c: Counts) -> None:
    """A2 bought 20 kg more (500 ₽/kg) and counted nothing left on 01.10: 10 + 170 + 5 received − 0 = 185
    used against 150 by the cards — 35 kg unexplained, 35 − 2 % × 150 = 32 kg beyond: 16 000 ₽; 16 000 × 30 /
    61 = 7 868,85 → 7 869 ₽ a month. A2's only period: no count before it."""
    _actual(owner_engine, c.a2, date(2026, 10, 1), c.cheese, "0")
    with Session(owner_engine) as s, s.begin():
        s.add(
            Receipt(
                tenant_id=c.tenant,
                restaurant_id=c.a2,
                import_batch_id=c.batch[c.a2],
                day=date(2026, 9, 2),
                doc_no="",
                product_id=c.cheese,
                qty=Decimal(20),
                amount=Decimal(10000),
            )
        )


# ------------------------------------------------------------------ № 13: the count's result


def test_a_restaurant_with_a_single_count_is_not_judged(counts: Counts, owner_engine: Engine) -> None:
    """A2 counted only once (01.10): no period between counts, nothing known — no director's note, and the
    HQ's summary neither lists A2 nor counts it «в допуске» (review of stage 12, p. 1: not judged ≠
    within)."""
    with Session(owner_engine) as s, s.begin():
        s.execute(
            delete(InventoryCount).where(
                InventoryCount.restaurant_id == counts.a2, InventoryCount.day == date(2026, 8, 1)
            )
        )
    service.run_all(TODAY)
    notes = _notes(owner_engine, "count_result")
    assert [n.key for n in notes if n.audience == "director"] == ["count_result:A1:2026-10-01"]
    (net,) = [n for n in notes if n.audience == "hq"]
    assert (net.facts["counted"], net.facts["within"]) == (1, 0)
    assert [x["code"] for x in net.facts["restaurants"]] == ["A1"]


def test_differences_under_the_threshold_say_nothing_to_the_director(
    counts: Counts, owner_engine: Engine
) -> None:
    """Beyond the allowance, but under `M1_MATERIALITY_RUB_MONTH` (3 000 ₽ a month):
    1) A1 left 42 kg of cheese: 10 + 200 − 5 − 42 = 163 used, 13 unexplained, 13 − 3 = 10 kg beyond = 5 000 ₽,
       5 000 × 30 / 61 = 2 459 ₽ a month; before — 1 721 ₽: grown by 738 < 3 000. Fries are the network's
       card. No note to anybody (A2 is within).
    2) The fries' card closed and A1 left 40 kg of fries: 200 − 150 − 40 = 10 unexplained, 10 − 3 = 7 kg
       beyond × 160 ₽ = 1 120 ₽ = 551 ₽ a month. Each product is under 3 000, together (5 000 + 1 120) ×
       30 / 61 = 3 009,84 → 3 010 ₽: the HQ sees A1, the director has nothing to explain and gets no note."""
    _actual(owner_engine, counts.a1, date(2026, 10, 1), counts.cheese, "42")
    service.run_all(TODAY)
    assert _notes(owner_engine, "count_result") == []

    _actual(owner_engine, counts.a1, date(2026, 10, 1), counts.fries, "40")
    with Session(owner_engine) as s, s.begin():
        s.execute(update(Finding).where(Finding.key == "M1:net:P11").values(status="resolved"))
    service.run_all(TODAY)
    notes = [n for n in _notes(owner_engine, "count_result") if n.status == "new"]
    assert [n.audience for n in notes] == ["hq"]
    (a1,) = notes[0].facts["restaurants"]
    assert (a1["month"], a1["before"], a1["grew"], a1["top"], a1["top_rub"], a1["director"]) == (
        "3010",
        "1721",
        False,
        "Сыр",
        "5000",
        0,
    )
    assert notes[0].facts["card_products"] == []
    assert notes[0].title == "Итоги инвентаризаций: расхождения сверх допуска"
    assert _plain(notes[0].items[0]).endswith(
        "директору объяснять нечего: каждый товар меньше 3 000 ₽ в месяц"
    )


def test_a_period_with_no_priced_product_names_no_rubles(counts: Counts, owner_engine: Engine) -> None:
    """A3 counted spices nobody in the network ever bought (no price, own or the network's) on 01.09 (50 kg)
    and 05.10 (0 kg); 1 000 soups × 0,01 kg = 10 kg by the cards: 40 kg unexplained, but no price — no rubles
    are invented: no director's note for A3, no line of A3 in the HQ's summary, and A3 is not «в допуске»
    either (before the fix it was: «в допуске — 2»)."""
    with Session(owner_engine) as s, s.begin():
        spice = Product(tenant_id=counts.tenant, code="P30", name="Специи", base_unit="kg")
        soup = MenuItem(tenant_id=counts.tenant, code="M30", name="Суп")
        s.add_all([spice, soup])
        s.flush()
        s.add(
            RecipeLine(
                tenant_id=counts.tenant,
                menu_item_id=soup.id,
                product_id=spice.id,
                gross_qty=Decimal("0.01"),
                valid_from=date(2025, 1, 1),
            )
        )
        s.add(
            Sale(
                tenant_id=counts.tenant,
                restaurant_id=counts.a3,
                import_batch_id=counts.batch[counts.a3],
                day=date(2026, 9, 20),
                menu_item_id=soup.id,
                qty=Decimal(1000),
                revenue=Decimal(1),
            )
        )
        spice_id = spice.id
    _count(owner_engine, counts, date(2026, 9, 1), spice_id, "50", counts.a3)
    _count(owner_engine, counts, date(2026, 10, 5), spice_id, "0", counts.a3)
    service.run_all(TODAY)
    notes = _notes(owner_engine, "count_result")
    assert [n.restaurant_id for n in notes if n.audience == "director"] == [counts.a1]
    (net,) = [n for n in notes if n.audience == "hq"]
    assert [x["code"] for x in net.facts["restaurants"]] == ["A1"]
    assert all("Специи" not in line for line in net.items)
    # Counted, but neither beyond in rubles nor «в допуске»: A2 is within, A3 is not known (bug fixed here)
    assert (net.facts["counted"], net.facts["within"]) == (3, 1)
    assert "в допуске — 1, без цены закупки не оценить — 1." in _plain(net.text)


def test_the_hq_summary_with_a_restaurant_without_a_count_before(
    counts: Counts, owner_engine: Engine
) -> None:
    """A2 goes beyond the allowance on its only period (`_a2_beyond`: 7 869 ₽ a month, before — None): not
    «grown» (nothing to compare with), listed after A1, which grew (1 721 → 7 869); its line has no «на
    прошлом пересчете». Title: grown in 1 of 2."""
    _a2_beyond(owner_engine, counts)
    service.run_all(TODAY)
    (net,) = [n for n in _notes(owner_engine, "count_result") if n.audience == "hq"]
    rows = [(x["code"], x["month"], x["before"], x["grew"], x["director"]) for x in net.facts["restaurants"]]
    assert rows == [("A1", "7869", "1721", True, 1), ("A2", "7869", None, False, 1)]
    assert (net.facts["counted"], net.facts["within"], net.facts["grew"]) == (2, 0, 1)
    assert net.title == "Итоги инвентаризаций: расхождения заметно выросли в 1 из 2"
    assert _plain(net.items[1]) == (
        "Сеть А A2 (01.10): сверх допуска ≈ 7 869 ₽ в месяц; больше всего — Сыр, 16 000 ₽ за период; "
        "директору — 1 товар к объяснению"
    )
    assert _plain(net.text).startswith(
        "Пересчитали 2 ресторана за последние три недели. Сверх допуска потерь"
    )
    # A2's own note: its own price (85 000 ₽ / 170 kg = 500 ₽/kg), not the network's
    (a2,) = [n for n in _notes(owner_engine, "count_result") if n.restaurant_id == counts.a2]
    assert [(p["qty"], p["rub"], p["network_price"]) for p in a2.facts["products"]] == [
        ("32", "16000", False)
    ]


def test_the_allowance_is_the_categorys_from_the_norms(counts: Counts, owner_engine: Engine) -> None:
    """The HQ's norms: cheese is «Сыры», 5 % allowed: A1's 35 kg unexplained − 5 % × 150 = 27,5 kg beyond ×
    500 ₽ = 13 750 ₽ (not 32 kg / 16 000 ₽ at the default 2 %)."""
    with Session(owner_engine) as s, s.begin():
        s.execute(update(Product).where(Product.id == counts.cheese).values(category="Сыры"))
    _norms(owner_engine, counts.tenant, loss_by_category={"Сыры": "5"})
    service.run_all(TODAY)
    (mine,) = [n for n in _notes(owner_engine, "count_result") if n.restaurant_id == counts.a1]
    assert [(p["qty"], p["rub"]) for p in mine.facts["products"]] == [("27.5", "13750")]


def test_the_directors_list_keeps_five_from_the_threshold_without_the_networks_card(
    counts: Counts, owner_engine: Engine
) -> None:
    """`_director` over a 30-day period (a month = the period): the network's card is left out of the list and
    the sum; a product at exactly 3 000 ₽ a month is in, 2 999,99 ₽ is not; no more than five, the costliest
    first."""
    period_start, period_end = date(2026, 9, 1), date(2026, 10, 1)
    products = {uuid4(): Product(code=f"P{i}", name=f"Товар {i}", base_unit="kg") for i in range(8)}
    ids = list(products)

    def excess(i: int, rub: str) -> count_agent.Excess:
        return count_agent.Excess(ids[i], Decimal(1), Decimal(rub), Decimal(1), Decimal(0))

    least = Decimal(3000)
    with Session(owner_engine) as s:
        r = s.get(Restaurant, counts.a1)
        assert r is not None
        cards = {ids[7]: "Товар 7"}
        few = count_agent.Period(
            period_start,
            period_end,
            [excess(7, "20000"), excess(0, "9000"), excess(1, "3000"), excess(2, "2999.99")],
            True,
        )
        d = count_agent._director(s, r, few, cards, products, least)
        assert d is not None
        assert [(p["code"], p["rub"]) for p in d.facts["products"]] == [("P0", "9000"), ("P1", "3000")]
        assert (d.facts["total_rub"], d.facts["card_products"]) == ("12000", ["Товар 7"])
        assert d.proposal is not None and len(d.proposal["checklist"]) == 2
        many = count_agent.Period(
            period_start, period_end, [excess(i, str(9000 - i * 1000)) for i in range(7)], True
        )
        d = count_agent._director(s, r, many, {}, products, least)
        assert d is not None
        assert [p["code"] for p in d.facts["products"]] == ["P0", "P1", "P2", "P3", "P4"]
        assert d.facts["total_rub"] == "35000"  # 9 000 + 8 000 + 7 000 + 6 000 + 5 000
        only_card = count_agent.Period(period_start, period_end, [excess(7, "20000")], True)
        assert count_agent._director(s, r, only_card, cards, products, least) is None


def test_a_director_asking_for_another_restaurant_gets_nothing(
    client: TestClient, counts: Counts, owner_engine: Engine
) -> None:
    """CLAUDE.md, p. 2: `?restaurant=` is a filter, not a pass — A1's director asking for A2 gets none of A2's
    notes (A2 has its own result, `_a2_beyond`) and cannot answer it; A2's director sees it; the other
    network's admin gets nothing for A1; the HQ analyst reads A2's list."""
    _a2_beyond(owner_engine, counts)
    service.run_all(TODAY)
    (a2_note,) = [n for n in _notes(owner_engine, "count_result") if n.restaurant_id == counts.a2]
    director1 = login(client, "director1@a.ru")

    def listed(headers: dict[str, str], restaurant: Any) -> list[tuple[str, str]]:
        r = client.get("/api/agents/notes", params={"restaurant": str(restaurant)}, headers=headers)
        assert r.status_code == 200
        return [(n["agent"], n["restaurant_id"]) for n in r.json() if n["agent"] == "count_result"]

    assert listed(director1, counts.a2) == []
    assert [a for a, _ in listed(director1, counts.a1)] == ["count_result"]
    assert listed(login(client, "director2@a.ru"), counts.a2) == [("count_result", str(counts.a2))]
    assert listed(login(client, "admin@b.ru"), counts.a1) == []
    assert listed(login(client, "analyst@a.ru"), counts.a2) == [("count_result", str(counts.a2))]
    for action in ("accept", "dismiss"):
        assert client.post(f"/api/agents/notes/{a2_note.id}/{action}", headers=director1).status_code == 404
        assert (
            client.post(f"/api/agents/notes/{a2_note.id}/{action}", headers=login(client, "admin@b.ru"))
        ).status_code == 404


# ------------------------------------------------------------------ № 14: menu prices


def test_the_food_cost_target_is_the_menu_categorys(menu: Menu, owner_engine: Engine) -> None:
    """The HQ's norms by menu category: «Горячее» 24 %, the rest 50 %.
    - «Лосось гриль» 1 000 ₽: 200 ₽ (20 %) → 320 ₽ (32 %) > 24 %. Price: 320 / 0,24 = 1 333,33 → 1 340 ₽
      (up to 10 ₽). Portion: 320 − 240 = 80 ₽ over, 80 / 1 600 = 0,05 kg: 0,200 → 0,150 — exactly a
      quarter, allowed.
    - «Паста» 160 ₽ (16 %) — within; «Тартар» 40 % before — «already».
    - «Суп» («Супы», 50 %): 20 / 50 = 40 % — within: no note about the new sauce."""
    _norms(
        owner_engine, menu.tenant, food_cost_target_pct=Decimal(50), food_cost_by_category={"Горячее": "24"}
    )
    service.run_all(TODAY)
    notes = {n.key: n for n in _notes(owner_engine, "menu_price")}
    assert sorted(notes) == ["menu_price:M3:net:P09:growth"]
    f = notes["menu_price:M3:net:P09:growth"].facts
    grill = next(d for d in f["dishes"] if d["code"] == "G")
    assert (grill["target_pct"], grill["new_price"], grill["cut"]) == (
        "24.0",
        "1340.00",
        {"old": "0.200", "new": "0.150"},
    )
    assert f["already"] == 1


def test_a_dish_exactly_at_the_target_was_within_and_a_big_cut_is_not_proposed(
    menu: Menu, owner_engine: Engine
) -> None:
    """«Горячее» 20 %: «Лосось гриль» was at 200 / 1 000 = 20 % — at the target is within, so it is listed;
    320 − 200 = 120 ₽ over = 0,075 kg of 0,2 (37,5 % > 25 %): no portion, the price only — 320 / 0,2 =
    1 600 ₽."""
    _norms(owner_engine, menu.tenant, food_cost_by_category={"Горячее": "20"})
    service.run_all(TODAY)
    (price,) = [n for n in _notes(owner_engine, "menu_price") if n.key == "menu_price:M3:net:P09:growth"]
    rows = {d["code"]: (d["food_cost_before_pct"], d["new_price"], d["cut"]) for d in price.facts["dishes"]}
    assert rows["G"] == ("20.0", "1600.00", None)
    assert "P" not in rows  # 16 % — within the 20 % still
    assert all(" или " not in line for line in price.items)


def test_menu_prices_are_the_same_twice(menu: Menu, owner_engine: Engine) -> None:
    """CLAUDE.md, p. 4: the second run of the day changes nothing."""
    service.run_all(TODAY)
    first = {(n.key, n.status, n.text, tuple(n.items)) for n in _notes(owner_engine, "menu_price")}
    service.run_all(TODAY)
    assert {(n.key, n.status, n.text, tuple(n.items)) for n in _notes(owner_engine, "menu_price")} == first


# ------------------------------------------------------------------ the model's text: only the facts' numbers


def _reply(text: str) -> Any:
    def reply(request: ModelRequest) -> Reply:
        return text_reply(json.dumps({"text": text}, ensure_ascii=False))

    return reply


def _writes(tenant: Any, agent: str, note: AgentNote, text: str) -> tuple[str, int] | None:
    model = FakeModel()
    model.replies += [_reply(text)] * 2
    with get_sessionmaker()() as s:
        return agent_writer.writer(Gateway(model), system_context(s, tenant))(agent, note.facts, note.text)


def test_the_model_quotes_only_the_counts_facts(counts: Counts, owner_engine: Engine) -> None:
    """CLAUDE.md, p. 1: the director's note — 32 kg, 16 000 ₽ are facts; «40 кг на 20 000 ₽» are not. The HQ's
    summary — 1 721 → 7 869 ₽ are facts; «12 000 ₽» is not. Refused twice — None, the rules' text stays."""
    service.run_all(TODAY)
    notes = _notes(owner_engine, "count_result")
    (mine,) = [n for n in notes if n.audience == "director"]
    (net,) = [n for n in notes if n.audience == "hq"]
    good = "Сыр ушел сверх допуска на 32 кг, это 16 000 ₽: начните со списаний."
    assert _writes(counts.tenant, "count_result", mine, good) == (good, 4)
    assert _writes(counts.tenant, "count_result", mine, "Сыр ушел на 40 кг, это 20 000 ₽.") is None
    good = "Расхождения выросли с 1 721 ₽ до 7 869 ₽ в месяц."
    assert _writes(counts.tenant, "count_result", net, good) == (good, 4)
    assert _writes(counts.tenant, "count_result", net, "Расхождения выросли до 12 000 ₽ в месяц.") is None


def test_the_model_quotes_only_the_menu_prices_facts(menu: Menu, owner_engine: Engine) -> None:
    """CLAUDE.md, p. 1: «Лосось» +60 %, «Лосось гриль» 1 070 ₽ — facts; 1 234 ₽ — not. Through the morning
    run: the model's text kept when it passes, the rules' text when it does not."""
    service.run_all(TODAY)
    (price,) = [n for n in _notes(owner_engine, "menu_price") if n.key == "menu_price:M3:net:P09:growth"]
    good = "Лосось подорожал на 60%: «Лосось гриль» за 1 070 ₽ вернется к цели 30%."
    assert _writes(menu.tenant, "menu_price", price, good) == (good, 4)
    assert _writes(menu.tenant, "menu_price", price, "Поднимите «Лосось гриль» до 1 234 ₽.") is None

    with Session(owner_engine) as s, s.begin():
        s.execute(delete(AgentNote))
    wrong = FakeModel()
    wrong.replies += [_reply("Поднимите «Лосось гриль» до 1 234 ₽.")] * 20
    service.run_all(TODAY, lambda ctx: agent_writer.writer(Gateway(wrong), ctx))
    for n in _notes(owner_engine, "menu_price"):
        assert n.source == "rules" and n.text == texts.menu_price(n.facts)[1]
        assert "1234" not in json.dumps(n.facts) and "1 234" not in _plain(n.text)


# ------------------------------------------------------------------ the rules' words


@pytest.mark.parametrize(
    ("n", "products", "restaurants", "dishes", "positions"),
    [
        (1, "1 товар", "1 ресторан", "1 блюда", "1 позиция"),
        (2, "2 товара", "2 ресторана", "2 блюд", "2 позиции"),
        (5, "5 товаров", "5 ресторанов", "5 блюд", "5 позиций"),
        (11, "11 товаров", "11 ресторанов", "11 блюд", "11 позиций"),
        (12, "12 товаров", "12 ресторанов", "12 блюд", "12 позиций"),
        (21, "21 товар", "21 ресторан", "21 блюда", "21 позиция"),
        (22, "22 товара", "22 ресторана", "22 блюд", "22 позиции"),
        (111, "111 товаров", "111 ресторанов", "111 блюд", "111 позиций"),
    ],
)
def test_the_plural_forms_of_the_stage_12_texts(
    n: int, products: str, restaurants: str, dishes: str, positions: str
) -> None:
    """«директору — 21 товар к объяснению», «Пересчитали 22 ресторана», «фудкост 21 блюда ушел»,
    «5 позиций»."""
    row = {
        "restaurant": "Р",
        "code": "R",
        "count_on": "2026-10-01",
        "month": "5000",
        "before": None,
        "grew": False,
        "top": None,
        "top_rub": None,
        "director": n,
    }
    net = {"restaurants": [row], "counted": n, "within": 0, "grew": 0, "least": "3000", "card_products": []}
    _title, text, items = texts.by_rules("count_result", net)
    assert _plain(items[0]).endswith(f"директору — {products} к объяснению")
    assert "больше всего" not in items[0] and "на прошлом пересчете" not in items[0]
    assert text.startswith(f"Пересчитали {restaurants} за последние три недели")

    product = {"name": "Сыр", "unit": "kg", "qty": "1", "rub": "1000", "hints": []}
    director = {
        "restaurant": "Р",
        "count_on": "2026-10-01",
        "since": "2026-08-01",
        "total_rub": "1000",
        "products": [product] * n,
        "card_products": [],
    }
    assert f"сверх допуска: {positions} на " in texts.by_rules("count_result", director)[1]

    dish = {
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
    card = {"reason": "card", "since": "2026-10-10", "already": 0, "dishes": [dish] * n}
    _title, text, items = texts.by_rules("menu_price", card)
    assert f"фудкост {dishes} ушел выше цели" in text
    assert len(items) == n  # no «already» line when there are none


def test_a_menu_note_without_sales_in_the_window_says_nothing(network: Network, owner_engine: Engine) -> None:
    """A price rise with no portions sold in the window: no margin to lose — no note (`portions_month`)."""
    a = network.a
    a1 = a.restaurants["A1"]
    with Session(owner_engine) as s, s.begin():
        salmon = Product(tenant_id=a.id, code="P09", name="Лосось", base_unit="kg")
        dish = MenuItem(
            tenant_id=a.id, code="G", name="Лосось гриль", category="Горячее", price=Decimal(1000)
        )
        s.add_all([salmon, dish])
        s.flush()
        s.add(
            RecipeLine(
                tenant_id=a.id,
                menu_item_id=dish.id,
                product_id=salmon.id,
                gross_qty=Decimal("0.2"),
                valid_from=date(2025, 1, 1),
            )
        )
        batch = _batch(s, a.id, a1, "any")
        for day, amount in ((date(2026, 6, 30), "100000"), (date(2026, 10, 18), "160000")):
            s.add(
                Receipt(
                    tenant_id=a.id,
                    restaurant_id=a1,
                    import_batch_id=batch,
                    day=day,
                    doc_no="",
                    product_id=salmon.id,
                    qty=Decimal(100),
                    amount=Decimal(amount),
                )
            )
        s.add(
            Sale(
                tenant_id=a.id,
                restaurant_id=a1,
                import_batch_id=batch,
                day=date(2026, 9, 1),  # before the window 21.09–18.10
                menu_item_id=dish.id,
                qty=Decimal(100),
                revenue=Decimal(100000),
            )
        )
        s.add(
            Finding(
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
        )
    service.run_all(TODAY)
    assert _notes(owner_engine, "menu_price") == []
