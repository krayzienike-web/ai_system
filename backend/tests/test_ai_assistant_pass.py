"""Test pass after the stage 5.5 code review (ADR 0008 with «Реализация» and «Уточнения», docs/09 «Адаптивный
импорт», docs/06 stage 5.5): the requirements the earlier tests did not prove. Registry: TC-AN-32…46."""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.ai import discover, precheck
from app.ai import prompt as prompts
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.ai.models import AiSuggestion
from app.catalog.models import MenuItem, Product, Supplier
from app.imports.models import ImportBatch, SourceProfile
from app.insights.models import Finding
from app.main import app
from app.operations.models import Receipt, Sale, WriteOff
from app.tenancy.context import tool_session
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _facts(r: ModelRequest) -> dict[str, Any]:
    facts: dict[str, Any] = json.loads(r.messages[0]["content"][0]["text"].split("\n", 1)[1])
    return facts


def _json(value: Any) -> Reply:
    return text_reply(json.dumps(value, ensure_ascii=False))


def _last_user_text(r: ModelRequest) -> str:
    text: str = r.messages[-1]["content"][0]["text"]
    return text


def _hypotheses(*, steps: list[str] | None = None, check: str = "на месте") -> Any:
    h = {"cause": "overordering", "likelihood": "высокая", "why": "по фактам", "check": check}
    return lambda _: _json({"hypotheses": [h], "steps": steps or [], "rules_note": None})


def _finding_id(owner_engine: Engine, network: Network, key: str) -> UUID:
    with Session(owner_engine) as s:
        return s.execute(
            select(Finding.id).where(Finding.tenant_id == network.a.id, Finding.key == key)
        ).scalar_one()


# ------------------------------------------------------------------ «Почему так»: the facts and the checks


@pytest.mark.usefixtures("demo")
def test_the_facts_hold_suppliers_by_month_and_the_restaurants_data_problems(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    """TC-AN-32 (docs/06 5.5 p. 2): «что менялось рядом» — who sold the product month by month and at what
    price; the data problems of the same restaurant (R10's mozzarella: the stock by documents goes
    negative)."""
    finding = _finding_id(owner_engine, network, "M1:R10:P01:under")
    model.replies.append(_hypotheses())
    made = client.post(f"/api/findings/{finding}/hypotheses", headers=login(client, "admin@a.ru")).json()
    facts = _facts(model.requests[0])
    months = facts["suppliers_by_month"]
    assert months and all({"month", "supplier", "avg_price", "bought"} <= set(m) for m in months)
    assert any("Моцарелла" in p for p in facts["data_problems"])
    assert "Моцарелла" in facts["product"]["name"]
    assert {"поставщики и цены по месяцам", "проблемы с данными ресторана"} <= set(made["basis_words"])


@pytest.mark.usefixtures("demo")
def test_a_data_problem_under_review_is_not_in_a_directors_basis(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    """TC-AN-33 (ADR 0008, «Уточнения»: nothing the director does not see on the card): a data problem of R01
    that waits for review (M7, `pending`) is not in the basis, though the HQ asked for the hypotheses."""
    with Session(owner_engine) as s, s.begin():
        r01 = s.execute(select(Finding.restaurant_id).where(Finding.key == "M1:R01:P01")).scalar_one()
        s.add(
            Finding(
                tenant_id=network.a.id,
                restaurant_id=r01,
                kind="problem",
                process="accounting",
                module="M7",
                title="СЕКРЕТ: проблема данных на проверке",
                actions=[],
                found_on=TODAY,
                review_status="pending",
            )
        )
    own = _finding_id(owner_engine, network, "M5:R01:P10")
    model.replies.append(_hypotheses())
    client.post(f"/api/findings/{own}/hypotheses", headers=login(client, "admin@a.ru"))
    assert "СЕКРЕТ" not in model.requests[0].messages[0]["content"][0]["text"]
    seen = client.get(f"/api/findings/{own}/hypotheses", headers=login(client, "r01@a.ru")).json()
    assert "СЕКРЕТ" not in json.dumps(seen, ensure_ascii=False)


@pytest.mark.usefixtures("demo")
def test_a_number_in_the_steps_or_in_how_to_check_is_checked_too(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    """TC-AN-34 (ADR 0008, «Уточнения»: numbers are checked in every factual field, not only in «why»)."""
    own = _finding_id(owner_engine, network, "M5:R01:P10")
    url = f"/api/findings/{own}/hypotheses"
    admin = login(client, "admin@a.ru")
    bad_steps = _hypotheses(steps=["Снизить заказ на 12 345 кг"])
    model.replies += [bad_steps, bad_steps]
    assert client.post(url, headers=admin).status_code == 502
    assert "12345" in _last_user_text(model.requests[1])  # asked to correct once, then no proposal
    bad_check = _hypotheses(check="Взвесить 37 порций")
    model.replies += [bad_check, bad_check]
    assert client.post(url, headers=admin).status_code == 502
    assert "37" in _last_user_text(model.requests[3])
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(AiSuggestion)).scalar_one() == 0


@pytest.mark.usefixtures("demo")
def test_a_proposal_records_its_prompt_version_and_a_replaced_one_cannot_be_decided(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    """TC-AN-35 (ADR 0008, «Реализация»: what was proposed, on what basis, the prompt's version, the decision;
    a new proposal replaces the old one — the old one is no longer decided on)."""
    own = _finding_id(owner_engine, network, "M5:R01:P10")
    director = login(client, "r01@a.ru")
    model.replies += [_hypotheses(), _hypotheses()]
    old = client.post(f"/api/findings/{own}/hypotheses", headers=director).json()
    new = client.post(f"/api/findings/{own}/hypotheses", headers=director).json()
    with Session(owner_engine) as s:
        row = s.get(AiSuggestion, UUID(new["id"]))
        assert row is not None
        assert (
            (row.prompt, row.prompt_version)
            == ("hypotheses", prompts.load("hypotheses").version)
            == (
                "hypotheses",
                2,
            )
        )
        assert row.created_by is not None and row.decided_by is None
        assert row.restaurant_id is not None and row.basis["finding"]["title"]
    decision = {"accepted": True}
    assert (
        client.post(f"/api/ai/suggestions/{old['id']}/decision", headers=director, json=decision).status_code
        == 404
    )
    assert (
        client.post(f"/api/ai/suggestions/{new['id']}/decision", headers=director, json=decision).status_code
        == 200
    )


# ------------------------------------------------------------------ the pre-check: the code's flags


def _batch(s: Session, tenant: UUID, restaurant: UUID) -> UUID:
    batch = ImportBatch(
        tenant_id=tenant,
        restaurant_id=restaurant,
        template="write_offs",
        filename="test.csv",
        sha256="0" * 64,
        raw=b"",
        status="published",
    )
    s.add(batch)
    s.flush()
    return batch.id


def _finding(tenant: UUID, restaurant: UUID, key: str, start: date, end: date) -> Finding:
    return Finding(
        tenant_id=tenant,
        restaurant_id=restaurant,
        kind="problem",
        process="production",
        module="M5",
        key=key,
        title=key,
        actions=[],
        found_on=end,
        period_from=start,
        period_to=end,
    )


def test_a_one_off_spike_a_new_supplier_and_a_holiday_by_the_spike_are_flagged(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-AN-36 (ADR 0008; docs/06 5.5 p. 3: «разовый всплеск», «смена поставщика»; code review p. 12: a
    holiday counts only by the spike's day in a long period). The verification is stubbed: not this test's."""
    monkeypatch.setattr(precheck, "verify", lambda *_: {})
    a, a1 = network.a.id, network.a.restaurants["A1"]
    with Session(owner_engine) as s, s.begin():
        batch = _batch(s, a, a1)
        p1, p2, p3 = (
            Product(tenant_id=a, code=c, name=f"Товар {c}", base_unit="kg") for c in ("P1", "P2", "P3")
        )
        s1, s2 = (
            Supplier(tenant_id=a, code="S1", name="Старый"),
            Supplier(tenant_id=a, code="S2", name="Новый"),
        )
        s.add_all([p1, p2, p3, s1, s2])
        s.flush()

        def off(p: Product, day: date, qty: int) -> WriteOff:
            return WriteOff(
                tenant_id=a,
                restaurant_id=a1,
                import_batch_id=batch,
                day=day,
                product_id=p.id,
                qty=Decimal(qty),
            )

        def got(p: Product, day: date, supplier: Supplier) -> Receipt:
            return Receipt(
                tenant_id=a,
                restaurant_id=a1,
                import_batch_id=batch,
                day=day,
                product_id=p.id,
                supplier_id=supplier.id,
                qty=Decimal(5),
                amount=Decimal("500.00"),
            )

        april = (date(2026, 4, 1), date(2026, 4, 30))  # 30 days, no public holiday
        # P1: write-offs 1 + 1 + 8 = 10, the 17th holds 8/10 = 80 % ≥ 50 % → a spike. Receipts: S1 before the
        # period (10.03), S2 in it (05.04) — S2 never sold P1 in the 60 days before → a change of supplier.
        s.add_all([off(p1, date(2026, 4, d), q) for d, q in ((3, 1), (10, 1), (17, 8))])
        s.add_all(
            [got(p1, date(2026, 3, 10), s1), got(p1, date(2026, 4, 5), s2), got(p1, date(2026, 4, 12), s1)]
        )
        # P2: 3 + 3 + 4 = 10, the top day 4/10 = 40 % < 50 % → no spike; S1 before and in it → no change.
        s.add_all([off(p2, date(2026, 4, d), q) for d, q in ((3, 3), (10, 3), (17, 4))])
        s.add_all([got(p2, date(2026, 3, 10), s1), got(p2, date(2026, 4, 5), s1)])
        # P3: 01.04–31.05 (61 days > 31): 1 + 8 + 1, the spike is on 09.05 → the holiday next to it is named,
        # 01.05 (8 days away) is not.
        s.add_all([off(p3, date(2026, 5, d), q) for d, q in ((2, 1), (9, 8), (20, 1))])
        s.flush()

        one = {f.code: f for f in precheck.flags(s, _finding(a, a1, "M5:A1:P1", *april), TODAY)}
        two = precheck.flags(s, _finding(a, a1, "M5:A1:P2", *april), TODAY)
        three = {
            f.code: f
            for f in precheck.flags(
                s, _finding(a, a1, "M5:A1:P3", date(2026, 4, 1), date(2026, 5, 31)), TODAY
            )
        }
        s.rollback()
    assert set(one) == {"one_off", "supplier_change"}
    assert one["one_off"].note == "Больше половины списаний товара за период — 17.04.2026"
    assert two == []
    assert set(three) == {"one_off", "holidays"} and three["holidays"].note == "09.05"


def test_a_failed_verification_is_flagged(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-AN-36: «непрошедшая сверка» — the step-by-step verification's failed checks are named, passed ones
    are not."""
    checks = [{"check": "Итог сходится с движком", "ok": False}, {"check": "Остатки есть", "ok": True}]
    monkeypatch.setattr(precheck, "verify", lambda *_: {"checks": checks})
    a, a1 = network.a.id, network.a.restaurants["A1"]
    with Session(owner_engine) as s:
        out = precheck.flags(
            s, _finding(a, a1, "M4:A1:pre-count", date(2026, 4, 1), date(2026, 4, 30)), TODAY
        )
    assert [(f.code, f.note) for f in out] == [("verification", "Итог сходится с движком")]


@pytest.mark.usefixtures("demo")
def test_a_draft_names_a_reason_only_when_it_rejects(
    client: TestClient, network: Network, owner_engine: Engine, model: FakeModel
) -> None:
    """TC-AN-37 (TC-AN-09, the other half): «подтвердить» with a reason is corrected, then no draft."""
    pending = _finding_id(owner_engine, network, "M6:R04:P15:shortage")
    body = {"verdict": "confirm", "reason": "data", "rationale": "По фактам", "look_at": []}
    model.replies += [lambda _: _json(body), lambda _: _json(body)]
    r = client.post(f"/api/findings/{pending}/precheck", headers=login(client, "analyst@a.ru"))
    assert r.status_code == 502 and "причина нужна только" in _last_user_text(model.requests[1])


# ------------------------------------------------------------------ ideas of new findings


def test_the_aggregates_skip_rare_write_offs_and_compare_with_the_network(
    network: Network, owner_engine: Engine
) -> None:
    """TC-AN-38 (ADR 0008: aggregates by the code; code review p. 11: by product, at least 4 days with
    write-offs). Today 20.10.2026, the window is the 8 weeks after 25.08.2026."""
    a = network.a.id
    places = network.a.restaurants
    with Session(owner_engine) as s, s.begin():
        bread = Product(tenant_id=a, code="P1", name="Хлеб", base_unit="pcs")
        dish = MenuItem(tenant_id=a, code="M1", name="Суп")
        s.add_all([bread, dish])
        s.flush()
        for code in ("A1", "A2", "A3"):
            batch = _batch(s, a, places[code])
            # Revenue 10 000 ₽ in each restaurant.
            s.add(
                Sale(
                    tenant_id=a,
                    restaurant_id=places[code],
                    import_batch_id=batch,
                    day=date(2026, 9, 7),
                    menu_item_id=dish.id,
                    qty=Decimal(100),
                    revenue=Decimal("10000.00"),
                )
            )

            def off(day: date, qty: int, code: str = code, batch: UUID = batch) -> WriteOff:
                return WriteOff(
                    tenant_id=a,
                    restaurant_id=places[code],
                    import_batch_id=batch,
                    day=day,
                    product_id=bread.id,
                    qty=Decimal(qty),
                )

            mondays = [date(2026, 9, 7) + timedelta(weeks=w) for w in range(4)]
            if code == "A1":  # 4 Mondays × 5 + a Wednesday 5 = 25 pcs on 5 days; Monday 20/25 = 80 %
                s.add_all([off(d, 5) for d in mondays] + [off(date(2026, 9, 9), 5)])
            elif code == "A2":  # 3 Mondays × 1 = 3 pcs on 3 days: all on Mondays, but too few days — noise
                s.add_all([off(d, 1) for d in mondays[:3]])
            else:  # one a day for a week 07.09–13.09: 7 pcs, every weekday 1/7 = 14,3 % < 25 %
                s.add_all([off(date(2026, 9, 7) + timedelta(days=i), 1) for i in range(7)])
    with tool_session(network.a.users["admin@a.ru"], a) as (session, _):
        table = discover.aggregates(session, TODAY)
    weekday = [(r["restaurant"], r["weekday"], r["share_of_week"]) for r in table["write_offs_by_weekday"]]
    assert weekday == [("A1", "понедельник", "80%")]
    # Per 1000 ₽ of revenue: A1 25/10000×1000 = 2,5; A2 0,3; A3 0,7; the mean (2,5+0,3+0,7)/3 = 1,1(6).
    # A1: 2,5 / 1,1667 = 2,14 ≥ 1,5 → above the network; A2 0,26 and A3 0,6 are not.
    vs = table["write_offs_vs_network"]
    assert [(r["restaurant"], r["write_offs_per_1000_rub_revenue"], r["network_average"]) for r in vs] == [
        ("A1", "2,5", "1,17")
    ]
    assert [r["id"] for r in table["write_offs_by_weekday"] + vs] == ["a1", "a2"]


@pytest.mark.usefixtures("demo")
def test_an_idea_quotes_only_the_rows_it_points_at_and_there_are_at_most_five(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-39 (ADR 0008, «Реализация»: an idea's numbers must be in *its* rows, not anywhere in the table;
    the prompt asks for at most five)."""
    analyst = login(client, "analyst@a.ru")

    def rows(r: ModelRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        table = _facts(r)["write_offs_by_weekday"]
        first = table[0]
        other = next(x for x in table if x["share_of_week"] != first["share_of_week"])
        return first, other

    def borrowed(r: ModelRequest) -> Reply:
        first, other = rows(r)
        idea = {
            "title": "Списания по дням",
            "pattern": f"Доля {other['share_of_week']}",  # a number of another row
            "rows": [first["id"]],
            "why_it_matters": "Лишние заказы",
            "rule_sketch": "—",
        }
        return _json({"ideas": [idea]})

    model.replies += [borrowed, borrowed]
    assert client.post("/api/ai/finding-ideas", headers=analyst).status_code == 502

    def ideas(n: int) -> Any:
        def reply(r: ModelRequest) -> Reply:
            first, _ = rows(r)
            idea = {
                "title": "Списания по дням",
                "pattern": f"{first['share_of_week']} — {first['weekday']}",
                "rows": [first["id"]],
                "why_it_matters": "Лишние заказы",
                "rule_sketch": "—",
            }
            return _json({"ideas": [idea] * n})

        return reply

    model.replies += [ideas(6), ideas(5)]
    made = client.post("/api/ai/finding-ideas", headers=analyst).json()
    assert len(made) == 5 and "идей больше пяти" in _last_user_text(model.requests[3])


# ------------------------------------------------------------------ unfamiliar files and source profiles


ODD = "Когда;Что;Сколько;Деньги;Заметка\n" + "".join(
    f"0{d}.10.2026;Сыр;{d};{d}00;{note}\n" for d, note in ((1, "1"), (2, "2"), (3, "нет"), (4, "нет"))
)


def _mark(
    client: TestClient, headers: dict[str, str], content: str, restaurant: UUID, name: str = "f.csv"
) -> Any:
    return client.post(
        "/api/imports/mapping",
        headers=headers,
        data={"template": "receipts", "restaurant_id": str(restaurant)},
        files={"file": (name, content.encode(), "text/csv")},
    )


def _marking(*pairs: tuple[str, str]) -> Any:
    return lambda _: _json({"columns": [{"field": f, "header": h, "why": "по образцам"} for f, h in pairs]})


BASE = (("day", "Когда"), ("product_name", "Что"), ("amount", "Деньги"))


def test_a_marking_that_breaks_more_than_half_of_the_rows_goes_back_but_half_is_a_marking(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-40 (ADR 0008 p. 3, docs/06 5.5 p. 5: the import checks the marking on the file itself). «Заметка»
    as the quantity: rows 3 and 4 («нет») fail, 2 of 4 = 50 % — not more than half, so it is a marking with
    its errors shown. «Что» as the quantity: all 4 rows fail → back to the model once, then no proposal."""
    admin, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    broken = _marking(("day", "Когда"), ("product_name", "Деньги"), ("qty", "Что"), ("amount", "Сколько"))
    model.replies += [broken, broken]
    assert _mark(client, admin, ODD, a1).status_code == 502
    assert "ошибки в 4 строках из 4" in _last_user_text(model.requests[1])

    model.replies.append(_marking(*BASE, ("qty", "Заметка")))
    half = _mark(client, admin, ODD, a1).json()
    assert half["preview"]["rows"] == 4 and half["preview"]["rows_with_errors"] == 2
    assert len(model.requests) == 3  # accepted at once


def test_a_confirmation_that_clashes_saves_nothing_and_keeps_the_marking_open(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Engine
) -> None:
    """TC-AN-41 (ADR 0008, «Уточнения»: accepted only by confirming, the profile is created in the same
    transaction; a clashing profile is not saved). Two markings of two files read «Заметка» two ways."""
    admin, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    model.replies += [
        _marking(*BASE, ("qty", "Заметка")),
        _marking(*BASE, ("qty", "Сколько"), ("vat", "Заметка")),
    ]
    first = _mark(client, admin, ODD, a1).json()
    second = _mark(client, admin, ODD.replace("нет", "0"), a1, "g.csv").json()
    assert client.post(f"/api/imports/mapping/{first['id']}/confirm", headers=admin).status_code == 200
    clash = client.post(f"/api/imports/mapping/{second['id']}/confirm", headers=admin)
    assert clash.status_code == 409 and "Заметка".lower() in clash.json()["detail"].lower()
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(SourceProfile)).scalar_one() == 1
        row = s.get(AiSuggestion, UUID(second["id"]))
        assert row is not None and row.status == "proposed" and row.decided_by is None


def test_the_same_file_marked_again_replaces_the_undecided_marking(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-42 (TC-AN-23, the other half): the same file for the same restaurant — the new marking replaces
    the old one, which can no longer be confirmed; a second confirmation of the new one — 409."""
    admin, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    model.replies += [_marking(*BASE, ("qty", "Сколько")), _marking(*BASE, ("qty", "Сколько"))]
    old = _mark(client, admin, ODD, a1).json()
    new = _mark(client, admin, ODD, a1).json()
    assert client.post(f"/api/imports/mapping/{old['id']}/confirm", headers=admin).status_code == 404
    assert client.post(f"/api/imports/mapping/{new['id']}/confirm", headers=admin).status_code == 200
    assert client.post(f"/api/imports/mapping/{new['id']}/confirm", headers=admin).status_code == 409


def test_a_directors_profile_stays_in_their_restaurant(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-43 (TC-ISO; ADR 0008, «Уточнения»: a director's profile serves their restaurant). Another
    restaurant's director neither confirms the marking, nor sees the profile, nor deletes it; their files do
    not load by it; its owner may delete it."""
    d1, d2 = login(client, "director1@a.ru"), login(client, "director2@a.ru")
    a1, a2 = network.a.restaurants["A1"], network.a.restaurants["A2"]
    model.replies.append(_marking(*BASE, ("qty", "Сколько")))
    marked = _mark(client, d1, ODD, a1).json()
    assert client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=d2).status_code == 404
    profile = client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=d1).json()["profile_id"]
    assert [p["id"] for p in client.get("/api/imports/profiles", headers=d1).json()] == [profile]
    assert client.get("/api/imports/profiles", headers=d2).json() == []
    assert client.delete(f"/api/imports/profiles/{profile}", headers=d2).status_code == 404

    def upload(headers: dict[str, str], restaurant: UUID) -> Any:
        data = {"template": "receipts", "restaurant_id": str(restaurant)}
        files = {"file": ("next.csv", ODD.replace("10.2026", "11.2026").encode(), "text/csv")}
        return client.post("/api/imports", headers=headers, data=data, files=files).json()

    assert upload(d1, a1)["status"] != "failed"  # read by the profile
    other = upload(d2, a2)
    assert other["status"] == "failed" and other["markable"] is True
    assert client.delete(f"/api/imports/profiles/{profile}", headers=d1).status_code == 204


def test_a_network_profile_does_not_override_a_restaurants_own_reading(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-44 (ADR 0008, «Уточнения»: a clashing profile is not saved). The director of A1 confirmed
    «Заметка» as the quantity for A1; the HQ's network profile that reads it as VAT would change how A1's
    files load behind the director's back — refused."""
    d1, admin, a1 = login(client, "director1@a.ru"), login(client, "admin@a.ru"), network.a.restaurants["A1"]
    model.replies += [
        _marking(*BASE, ("qty", "Заметка")),
        _marking(*BASE, ("qty", "Сколько"), ("vat", "Заметка")),
    ]
    mine = _mark(client, d1, ODD, a1).json()
    assert client.post(f"/api/imports/mapping/{mine['id']}/confirm", headers=d1).status_code == 200
    # The HQ marks A2's file (A1's profile does not serve it), and confirms it — for the whole network.
    hq = _mark(client, admin, ODD.replace("нет", "0"), network.a.restaurants["A2"], "g.csv").json()
    refused = client.post(f"/api/imports/mapping/{hq['id']}/confirm", headers=admin)
    assert refused.status_code == 409 and "заметка" in refused.json()["detail"]
    # A1's next file still reads «Заметка» as the director confirmed (before the fix the later network profile
    # won the merge and A1's quantity column was lost).
    data = {"template": "receipts", "restaurant_id": str(a1)}
    files = {"file": ("next.csv", ODD.replace("нет", "3").encode(), "text/csv")}
    batch = client.post("/api/imports", headers=d1, data=data, files=files).json()
    assert (
        batch["status"] != "failed" and batch["column_map"]["Количество"] == "5"
    )  # the 5th column, «Заметка»


STRANGE = (
    "Справочник контрагентов\n\nИдентификатор;Юрлицо;Налоговый номер\n"
    "S1;ООО Ромашка;7701000001\nS2;ИП Лютиков;7701000002\n"
)


def test_a_changed_format_offers_a_new_marking_instead_of_failing(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AN-45 (docs/09 «Адаптивный импорт», p. 4: the format changed — the system notices the difference
    with the profile and offers to update the mapping, it does not break). The profile reads «Юрлицо»; next
    month the column is «Контрагент полностью»: the file is refused with «can be marked», the new marking
    keeps what the profile already maps and asks the model only for the renamed column."""
    admin = login(client, "admin@a.ru")

    def send(path: str, content: str, template: str | None = "suppliers") -> Any:
        data = {"template": template} if template else {}
        files = {"file": ("контрагенты.csv", content.encode(), "text/csv")}
        return client.post(path, headers=admin, data=data, files=files)

    model.replies.append(_marking(("code", "Идентификатор"), ("name", "Юрлицо"), ("inn", "Налоговый номер")))
    marked = send("/api/imports/mapping", STRANGE).json()
    assert client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=admin).status_code == 200
    renamed = STRANGE.replace("Юрлицо", "Контрагент полностью").replace("S1;", "S7;").replace("S2;", "S8;")
    refused = send("/api/imports", renamed).json()
    assert refused["status"] == "failed" and refused["markable"] is True
    guessed = send("/api/imports", renamed, None)
    assert guessed.status_code == 422 and guessed.json()["code"] == "no_header"
    model.replies.append(_marking(("name", "Контрагент полностью")))
    again = send("/api/imports/mapping", renamed).json()
    assert _facts(model.requests[1])["already_mapped"] == {"code": "Идентификатор", "inn": "Налоговый номер"}
    assert {c["field"]: c["header"] for c in again["columns"]} == {
        "code": "Идентификатор",
        "inn": "Налоговый номер",
        "name": "Контрагент полностью",
    }
    assert again["preview"]["rows_with_errors"] == 0


def test_a_marking_of_a_restaurants_file_is_kept_under_that_restaurant(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Engine
) -> None:
    """TC-AN-46 (ADR 0008, «Реализация»: visibility by restaurant, RLS): the proposal of a director's file
    belongs to their restaurant, with the file's headers and samples as its basis."""
    d1, a1 = login(client, "director1@a.ru"), network.a.restaurants["A1"]
    model.replies.append(_marking(*BASE, ("qty", "Сколько")))
    marked = _mark(client, d1, ODD, a1).json()
    with Session(owner_engine) as s:
        row = s.get(AiSuggestion, UUID(marked["id"]))
        assert row is not None
        assert (row.kind, row.restaurant_id, row.prompt) == ("mapping", a1, "mapping")
        assert row.basis["headers"] == ["Когда", "Что", "Сколько", "Деньги", "Заметка"]
        assert len(row.basis["samples"]) == 4


@pytest.mark.xfail(
    strict=True,
    reason="verify.unsupported refuses «половины» even when the code's own flag says it: a draft that quotes "
    "the pre-check's «Больше половины списаний…» is refused (TC-AN-49)",
)
def test_a_draft_may_quote_the_pre_checks_own_flag() -> None:
    """TC-AN-49 (ADR 0008: the numbers of a proposal are checked against the facts). The code's flag «Разовый
    всплеск» says «Больше половины…» (TC-AN-36); a draft repeating the fact the code gave it made nothing
    up."""
    from app.ai.verify import unsupported

    note = "Больше половины списаний товара за период — 17.04.2026"
    assert unsupported(f"Разовый всплеск: {note.lower()}", [{"flags": [{"note": note}]}]) == []
