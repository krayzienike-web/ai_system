"""Overview screens, actions and chat on the server (ADR 0007): figures, access rules, isolation."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.analytics import kpi
from app.analytics.costs import CostBook
from app.analytics.facts import Facts, MenuInfo, ProductInfo, ReceiptRow, SaleRow, WriteOffRow
from app.analytics.m1 import M1Row
from app.analytics.views import scale_answer
from app.core import words
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.core.security import hash_password
from app.demo import showcase
from app.demo.generator import generate
from app.demo.loader import load
from app.main import app
from app.tenancy.context import load_access_context
from app.tenancy.models import Restaurant, Role, RoleAssignment, User
from tests.conftest import PASSWORD, Network, login

D = Decimal
TODAY = date(2026, 10, 20)


# ------------------------------------------------------------------ pure functions


def test_words() -> None:
    assert words.rub(D(900)) == "900 ₽"
    assert words.rub(D(15197)) == "15,2 тыс ₽"
    assert words.rub(D(38000)) == "38 тыс ₽"
    assert words.rub(D(1250000)) == "1,25 млн ₽"
    assert [words.plural(n, ("задача", "задачи", "задач")) for n in (1, 2, 5, 11, 21, 104)] == [
        "1 задача",
        "2 задачи",
        "5 задач",
        "11 задач",
        "21 задача",
        "104 задачи",
    ]
    assert words.percent(D("0.20517")) == "20,5%"
    assert words.percent(None) == "—"


def test_scale_answer_says_how_far_and_which_way() -> None:
    base = {"network": None, "network_label": None, "norm": None, "norm_label": None}
    assert (
        scale_answer(
            {
                **base,
                "label": "Расход",
                "unit": "%",
                "me": 11.4,
                "network": 2.0,
                "norm": 1.5,
                "lower_is_better": True,
            }
        )
        == "Да. Расход: на 9,4 пункта выше, чем среднее по сети, при норме 1,5%."
    )
    assert (
        scale_answer(
            {**base, "label": "Цена", "unit": "₽/кг", "me": 1100, "network": 1000, "lower_is_better": True}
        )
        == "Да. Цена: на 10% выше, чем среднее по сети."
    )
    assert (
        scale_answer(
            {**base, "label": "Списания", "unit": "кг", "me": 33, "network": 10, "lower_is_better": True}
        )
        == "Да. Списания: в 3,3 раза выше, чем среднее по сети."
    )
    assert (
        scale_answer(
            {
                **base,
                "label": "Фудкост",
                "unit": "%",
                "me": 28.0,
                "norm": 30.0,
                "norm_label": "цель",
                "lower_is_better": True,
            }
        )
        == "Нет. Фудкост: на 2 пункта лучше, чем цель."
    )
    assert scale_answer({**base, "label": "X", "unit": "%", "me": 1.0, "lower_is_better": True}) is None


def test_kpis_are_shares_of_revenue_and_the_network_is_weighted_by_it() -> None:
    f = Facts()
    a, b, cheese, pizza = uuid4(), uuid4(), uuid4(), uuid4()
    f.restaurants = {a: "R01", b: "R02"}
    f.products = {cheese: ProductInfo("P01", "Сыр", "Сыры", "kg", 10, False)}
    f.menu = {pizza: MenuInfo("M01", "Пицца", "Пицца", D(500))}
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    # Food cost: A used 10 kg (recipes: 9) at 600 ₽ against 30 000 ₽ of revenue → 20 % actual, 18 % recipes.
    # B used 5 kg (recipes say 5) against 10 000 ₽ → 30 % and 30 %. Network: 9 000 / 40 000 = 22,5 %.
    rows = [
        M1Row(a, cheese, start, end, theory=D(9), actual=D(10), write_off=D(0), unit_cost=D(600)),
        M1Row(b, cheese, start, end, theory=D(5), actual=D(5), write_off=D(0), unit_cost=D(600)),
    ]
    f.sales = [SaleRow(a, end, pizza, D(60), D(30000)), SaleRow(b, end, pizza, D(20), D(10000))]
    f.receipts = [ReceiptRow(a, end - timedelta(days=3), cheese, None, D(10), D(6000))]
    # Write-offs of the last 28 days: A wrote off 1 kg × 600 ₽ = 600 ₽ of 30 000 ₽ → 2 %.
    f.write_offs = [WriteOffRow(a, end, cheese, D(1), "spoiled")]
    out = {k.restaurant: k for k in kpi.compute(f, rows, CostBook(f.receipts))}
    assert out[a].food_cost_actual == D("0.2") and out[a].food_cost_theory == D("0.18")
    assert out[b].food_cost_actual == D("0.3")
    assert out[None].food_cost_actual == D("0.225") and out[None].revenue == D(40000)
    assert out[a].write_offs_share == D("0.02") and out[b].write_offs_share == D(0)
    assert out[a].food_cost_from == start + timedelta(days=1) and out[a].food_cost_to == end


# ------------------------------------------------------------------ the demo network with its history


@pytest.fixture
def demo(network: Network, owner_engine: Engine) -> Iterator[dict[str, UUID]]:
    """The demo network in tenant A: 2 weeks of history, the work on findings and a director of R01."""
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        load(session, ctx, generate(seed=42), today=TODAY)
        showcase.build(session, ctx, network.a.users["analyst@a.ru"], TODAY, weeks=2)
        session.commit()
    with Session(owner_engine) as s, s.begin():
        r01 = s.execute(
            select(Restaurant.id).where(Restaurant.tenant_id == network.a.id, Restaurant.code == "R01")
        ).scalar_one()
        user = User(
            tenant_id=network.a.id, email="r01@a.ru", full_name="R01", password_hash=hash_password(PASSWORD)
        )
        s.add(user)
        s.flush()
        s.add(
            RoleAssignment(
                tenant_id=network.a.id, user_id=user.id, role=Role.RESTAURANT_DIRECTOR, restaurant_id=r01
            )
        )
    app.dependency_overrides[get_today] = lambda: TODAY
    yield {"R01": r01}
    app.dependency_overrides.pop(get_today, None)


def test_overview_screens_follow_the_access_rules(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    hq, analyst, director = (
        login(client, "admin@a.ru"),
        login(client, "analyst@a.ru"),
        login(client, "r01@a.ru"),
    )
    foreign = login(client, "admin@b.ru")

    ctx = client.get("/api/overview/context", headers=director).json()
    assert (ctx["today"], ctx["data_until"], ctx["next_count_on"]) == (
        "2026-10-20",
        "2026-10-18",
        "2026-11-29",
    )
    assert [(d["label"], d["due_on"]) for d in ctx["due_options"]][1] == ("Неделя", "2026-10-27")
    week = next(p for p in ctx["periods"] if p["preset"] == "week")
    assert (week["date_from"], week["date_to"]) == ("2026-10-12", "2026-10-18")

    net = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()
    assert net["restaurants"] == 15  # the 3 of the fixture and the 12 of the demo network
    # The money on the table is the sum of the open checked findings, the most expensive restaurant first.
    findings = client.get("/api/findings", headers=hq).json()
    open_problems = [f for f in findings if f["status"] != "resolved" and f["kind"] == "problem"]
    assert D(net["losses"]) == sum(D(f["effect_rub_month"] or 0) for f in open_problems)
    assert net["ranking"][0]["code"] == "R01" and net["ranking"][0]["top_problem"].endswith("Сыр Моцарелла")
    assert net["checks_waiting"] == 1 and net["completed_checks"] == 2 and net["overdue_tasks"] == 2
    assert D(net["confirmed"]) > 0  # the rocket check worked
    assert len(net["trend"]["labels"]) >= 2 and net["trend"]["labels"][-1] == "12.10"
    assert any(c["title"] == "«Тыквенный суп» продается без техкарты" for c in net["common"])
    assert client.get("/api/overview/network", headers=director).status_code == 403
    assert client.get("/api/overview/restaurants", headers=director).status_code == 403
    assert client.get("/api/overview/network", headers=foreign).json()["restaurants"] == 1

    rows = client.get("/api/overview/restaurants", headers=analyst).json()
    assert len(rows) == 15
    r01 = next(r for r in rows if r["code"] == "R01")
    assert D(r01["food_cost"]) > 0 and r01["tasks_total"] == 2

    week = client.get("/api/overview/restaurants/R01", headers=director).json()
    assert week["restaurant"]["code"] == "R01"
    assert week["digest"].startswith("Главное — «Перерасход по техкарте: Сыр Моцарелла»")
    assert all(f["restaurant_code"] == "R01" for f in week["top"])
    assert week["network_kpi"]["food_cost_actual"] and week["kpi"]["food_cost_actual"]
    assert week["kpi_answer"].startswith("Фудкост на ")
    assert week["results_answer"].startswith("Ваши задачи уже приносят +")  # the rocket task
    # Another restaurant of the network and another network: not found, like a missing one.
    assert client.get("/api/overview/restaurants/R02", headers=director).status_code == 404
    assert client.get("/api/overview/restaurants/R01", headers=foreign).status_code == 404

    assert client.get("/api/overview/badges", headers=hq).json() == {"inbox": 3, "open_tasks": 0}
    assert client.get("/api/overview/badges", headers=director).json() == {"inbox": 0, "open_tasks": 1}


def test_findings_carry_how_they_are_shown(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    director = login(client, "r01@a.ru")
    moz = next(
        f for f in client.get("/api/findings", headers=director).json() if f["title"].endswith("Моцарелла")
    )
    view = moz["view"]
    assert view["scale"]["answer"].startswith("Да. Расход сверх техкарты: на ")
    assert view["composition"]["answer"].startswith("Из израсходованных ")
    assert view["chart"]["labels"][-1] == "04.08–01.10" and len(view["table"]["rows"]) == 3
    detail = client.get(f"/api/findings/{moz['id']}", headers=director).json()
    assert detail["check"] is None  # a director follows a check through its tasks
    assert detail["result_answer"].startswith("В работе")
    assert detail["tasks"][0]["source"] == "Проверка «Контрольное взвешивание сыра»"


def test_task_checklist_and_reminders(client: TestClient, network: Network, demo: dict[str, UUID]) -> None:
    hq, director, other = (
        login(client, "admin@a.ru"),
        login(client, "r01@a.ru"),
        login(client, "director1@a.ru"),
    )
    mine = next(t for t in client.get("/api/tasks", headers=director).json() if t["checklist"])
    url = f"/api/tasks/{mine['id']}/checklist"
    assert client.post(url, headers=director, json={"index": 1, "done": True}).json()["checklist_done"] == [
        False,
        True,
    ]
    assert client.post(url, headers=director, json={"index": 9, "done": True}).status_code == 422
    assert client.post(url, headers=hq, json={"index": 0, "done": True}).status_code == 403
    assert (
        client.post(url, headers=other, json={"index": 0, "done": True}).status_code == 404
    )  # A1's director

    late = client.get("/api/tasks", headers=hq, params={"late": True}).json()
    assert {t["restaurant_code"] for t in late} == {"R03", "R05"}
    assert client.post(f"/api/tasks/{late[0]['id']}/remind", headers=hq).json()["reminded_on"] == "2026-10-20"
    assert client.post(f"/api/tasks/{late[0]['id']}/remind", headers=director).status_code == 403
    assert client.post(f"/api/tasks/{mine['id']}/remind", headers=hq).status_code == 422  # not overdue


def test_checks_are_drafted_proposed_and_rolled_out(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    hq, analyst, director = (
        login(client, "admin@a.ru"),
        login(client, "analyst@a.ru"),
        login(client, "r01@a.ru"),
    )
    foreign = login(client, "admin@b.ru")
    findings = client.get("/api/findings", headers=hq).json()
    cream = next(f for f in findings if f["title"].endswith("Сливки 33%"))
    draft = client.get("/api/checks/draft", headers=analyst, params={"finding_id": cream["id"]}).json()
    assert draft["test"]["code"] == "R05" and draft["default_weeks"] == 4
    assert sum(c["suggested"] for c in draft["candidates"]) == 3
    # 60 % of the finding, rounded to 100 ₽.
    assert (
        D(draft["expected_rub_month"]) == (D(cream["effect_rub_month"]) * D("0.6") / 100).quantize(D(1)) * 100
    )
    assert (
        client.get("/api/checks/draft", headers=director, params={"finding_id": cream["id"]}).status_code
        == 403
    )
    network_wide = next(f for f in findings if f["restaurant_id"] is None)
    assert (
        client.get("/api/checks/draft", headers=hq, params={"finding_id": network_wide["id"]}).status_code
        == 422
    )
    pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()[0]
    assert client.get("/api/checks/draft", headers=hq, params={"finding_id": pending["id"]}).status_code in (
        404,
        422,
    )

    control = [c["restaurant_id"] for c in draft["candidates"] if c["suggested"]]
    body = {"finding_id": cream["id"], "action": draft["actions"][0], "control_ids": control, "weeks": 4}
    assert (
        client.post("/api/checks", headers=analyst, json={**body, "action": "что-то другое"}).status_code
        == 422
    )
    proposed = client.post("/api/checks", headers=analyst, json=body).json()
    assert proposed["status"] == "proposed" and [p["code"] for p in proposed["test"]] == ["R05"]
    assert proposed["finding_title"] == cream["title"]
    # Code review 27.10.2026: a second click must not make a second check of the same finding.
    again = client.post("/api/checks", headers=analyst, json=body)
    assert again.status_code == 422 and "уже есть проверка" in again.json()["detail"]
    assert client.get(f"/api/checks/{proposed['id']}", headers=foreign).status_code == 404

    checks = client.get("/api/checks", headers=hq).json()
    worked = next(c for c in checks if c["verdict"] == "confirmed")
    detail = client.get(f"/api/checks/{worked['id']}", headers=hq).json()
    assert detail["tasks"][0]["outcome"]["verdict"] == "confirmed"
    assert client.post(f"/api/checks/{worked['id']}/rollout", headers=analyst).status_code == 403
    # Two «Ввести во всех ресторанах» at once (code review 27.10.2026): the tasks go out once.
    with ThreadPoolExecutor(2) as pool:
        answers = list(
            pool.map(lambda _: client.post(f"/api/checks/{worked['id']}/rollout", headers=hq), range(2))
        )
    assert sorted(a.status_code for a in answers) == [200, 422]
    tasks = next(a for a in answers if a.status_code == 200).json()
    assert len(tasks) == 14 and "R01" not in {t["restaurant_code"] for t in tasks}  # R01 already did it
    unclear = next(c for c in checks if c["verdict"] == "inconclusive")
    assert client.post(f"/api/checks/{unclear['id']}/rollout", headers=hq).status_code == 422


def test_head_report_and_chat(client: TestClient, network: Network, demo: dict[str, UUID]) -> None:
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    report = client.get("/api/reports/head", headers=hq, params={"preset": "13w"}).json()
    assert report["network_name"] == "Сеть А" and len(report["checks"]) == 4
    assert D(report["confirmed_by_tasks_rub_month"]) == sum(
        D(t["outcome"]["effect_rub_month"] or 0)
        for t in report["done_tasks"]
        if t["outcome"] and t["outcome"]["verdict"] == "confirmed"
    )
    assert len(report["trend"]["labels"]) >= 2
    assert {f["where"] for f in report["failures"]} >= {"Ресторан на Баумана"}

    chat = client.post(
        "/api/chat", headers=director, json={"question": "Почему у меня вырос фудкост?"}
    ).json()
    assert [r[0] for r in chat["rows"]] == ["Ресторан на Тверской", "Среднее по сети"]  # nobody else's
    other = client.post("/api/chat", headers=director, json={"question": "Сравни с Арбатом"}).json()
    assert other["text"].startswith("Данные других ресторанов вам недоступны")
    assert "Арбат" not in str(other["rows"])
    hq_chat = client.post("/api/chat", headers=hq, json={"question": "Сравни рестораны по фудкосту"}).json()
    assert len(hq_chat["rows"]) == 12  # restaurants with data
    checks = client.post("/api/chat", headers=hq, json={"question": "Какие проверки сработали?"}).json()
    assert checks["text"].startswith("Завершено 2 проверки, сработало 1")
    assert client.get("/api/chat/suggestions", headers=director).json()[0] == "Почему у меня вырос фудкост?"
    # Code review 27.10.2026: the shortage question is answered from the checked M6 findings (R04's pasta).
    pending = client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
    pasta = next(f for f in pending if f["module"] == "M6")
    client.post(f"/api/findings/{pasta['id']}/review", headers=hq, json={"verdict": "confirm"})
    stock = client.post("/api/chat", headers=hq, json={"question": "Что закончится до поставки?"}).json()
    assert "в разработке" not in stock["text"] and any("спагетти" in r[1].lower() for r in stock["rows"])


def test_findings_board_filters_counts_and_sums(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    board = client.get("/api/overview/findings", headers=hq).json()
    findings = client.get("/api/findings", headers=hq).json()
    assert board["stage_counts"]["all"] == len(findings)
    problems = next(k for k in board["kinds"] if k["kind"] == "problem")
    assert D(problems["total"]) == sum(
        D(f["effect_rub_month"] or 0) for f in findings if f["kind"] == "problem"
    )
    # The most expensive first; findings without a ruble estimate in their own group, last.
    first = board["groups"][0]
    assert first["key"] == "problem"
    effects = [D(f["effect_rub_month"]) for f in first["items"]]
    assert effects == sorted(effects, reverse=True)
    assert board["groups"][-1]["key"] == "unestimated"
    net = client.get("/api/overview/findings", headers=hq, params={"restaurant": "net"}).json()
    assert all(f["restaurant_id"] is None for g in net["groups"] for f in g["items"])
    late = client.get("/api/overview/findings", headers=hq, params={"late": True}).json()
    assert all(f["work"]["tasks_late"] > 0 for g in late["groups"] for f in g["items"])
    # A director's board holds only their restaurant.
    mine = client.get("/api/overview/findings", headers=director).json()
    assert {f["restaurant_code"] for g in mine["groups"] for f in g["items"]} == {"R01"}


def test_a_check_draft_for_a_restaurant_without_revenue_yet(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    """Code review 27.10.2026: no revenue in the KPIs (no stock-count period yet) must not divide by zero."""
    hq = login(client, "admin@a.ru")
    cream = next(
        f for f in client.get("/api/findings", headers=hq).json() if f["title"].endswith("Сливки 33%")
    )
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE kpi_snapshots SET revenue = 0 WHERE restaurant_id = :r"),
            {"r": cream["restaurant_id"]},
        )
    draft = client.get("/api/checks/draft", headers=hq, params={"finding_id": cream["id"]})
    assert draft.status_code == 200 and len(draft.json()["candidates"]) > 0


def test_new_endpoints_keep_to_the_tenant_and_the_restaurant(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    """Code review 27.10.2026: isolation of the endpoints added in stage 3 (CLAUDE.md, principle 2)."""
    hq, director, foreign = (
        login(client, "admin@a.ru"),
        login(client, "r01@a.ru"),
        login(client, "admin@b.ru"),
    )
    findings = client.get("/api/findings", headers=hq).json()
    beef = next(f for f in findings if f["title"].startswith("Закупка у дорогого поставщика"))  # R02
    network_wide = next(f for f in findings if f["restaurant_id"] is None)
    # The chat about a finding the asker may not see says nothing of it.
    for headers, f in ((director, beef), (director, network_wide), (foreign, beef)):
        answer = client.post(
            "/api/chat", headers=headers, json={"question": "Почему так?", "finding_id": f["id"]}
        )
        assert answer.status_code == 200
        body = answer.json()
        assert body["source_finding_id"] != f["id"] and f["title"] not in body["text"], f["title"]
    # Another tenant can neither remind about the tasks nor roll the checks out.
    late = client.get("/api/tasks", headers=hq, params={"late": True}).json()[0]
    assert client.post(f"/api/tasks/{late['id']}/remind", headers=foreign).status_code == 404
    worked = next(c for c in client.get("/api/checks", headers=hq).json() if c["verdict"] == "confirmed")
    assert client.post(f"/api/checks/{worked['id']}/rollout", headers=foreign).status_code == 404
    # The findings board of a director holds their restaurant only; another tenant's board is empty.
    board = client.get("/api/overview/findings", headers=director).json()
    places = {f["restaurant_code"] for g in board["groups"] for f in g["items"]}
    assert places == {"R01"}
    assert client.get("/api/overview/findings", headers=foreign).json()["groups"] == []
    # Other restaurants' prices by name are HQ's: a director's view of an M3 finding has no such table.
    from app.insights.api import _view_for
    from app.tenancy.context import AccessContext

    view = {
        "summary": "…",
        "table": {"rows": [["Ресторан на Арбате", 1132.0]]},
        "table_names_restaurants": True,
    }
    as_director = AccessContext(
        network.a.users["director1@a.ru"], network.a.id, Role.RESTAURANT_DIRECTOR, None
    )
    as_hq = AccessContext(network.a.users["admin@a.ru"], network.a.id, Role.HQ_ADMIN, None)
    assert "table" not in (_view_for(view, as_director) or {})
    assert (_view_for(view, as_hq) or {})["table"] == view["table"]
