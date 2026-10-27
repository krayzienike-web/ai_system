"""Overview screens, actions and chat on the server (ADR 0007): figures, access rules, isolation."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
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
from app.insights.models import Finding
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


def test_trend_line_in_figures_and_words() -> None:
    """TC-OVR-11 (ADR 0007): the change of «найденный потенциал», its % and the answer come from
    the server."""
    from app.overview.service import Trend
    from app.reports.api import _trend_answer

    down = Trend(on_table=[D(12000), D(10500), D(9000)])
    # 9 000 − 12 000 = −3 000 ₽ a month; 3 000 / 12 000 = 25 %; three points are two weeks of change.
    assert down.change == D(-3000) and down.change_pct == 25 and down.span == "2 недели"
    assert down.answer == "Да. За 2 недели найденный потенциал снизился с 12 тыс ₽ до 9 тыс ₽ в месяц."
    assert _trend_answer(down, 4, 6) == (
        "За 2 недели найденный потенциал снизился с 12 тыс ₽ до 9 тыс ₽ в месяц, "
        "открытых находок — 4 (было 6)."
    )
    up = Trend(on_table=[D(8000), D(9000), D(9500), D(10000), D(10000), D(10000)])
    # +2 000 ₽ over 5 weeks; 2 000 / 8 000 = 25 %.
    assert (up.change, up.change_pct, up.span) == (D(2000), 25, "5 недель")
    assert up.answer.startswith("Нет. За 5 недель найденный потенциал вырос с 8 тыс ₽ до 10 тыс ₽ в месяц")
    flat = Trend(on_table=[D(900), D(900)])
    assert (flat.change, flat.change_pct, flat.span) == (D(0), 0, "1 неделю")
    assert flat.answer == "Пока нет. За 1 неделю найденный потенциал не изменился: 900 ₽ в месяц."
    assert _trend_answer(flat, 2, 2).startswith(
        "За 1 неделю найденный потенциал не изменился — 900 ₽ в месяц"
    )
    # 12,5 % rounds half up, as everywhere in the engine (not to the even 12).
    assert Trend(on_table=[D(8000), D(7000)]).change_pct == 13
    # Nothing found at first: no percentage of zero, the answer still in words.
    from_zero = Trend(on_table=[D(0), D(500)])
    assert from_zero.change == D(500) and from_zero.change_pct is None
    single = Trend(on_table=[D(500)])
    assert single.change is None and single.answer == "История появится после двух недель пересчетов."
    assert (
        _trend_answer(single, 3, 0) == "Открытых находок — 3. История появится после двух недель пересчетов."
    )


def test_totals_a_year_and_the_trend_come_from_the_api(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    """TC-OVR-11 (code review 27.10.2026, frontend 1): the screens show these figures as they come."""
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    net = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()
    # «Найденный потенциал» = losses + potential a month; a year is 12 months of it.
    assert D(net["on_table"]) == D(net["losses"]) + D(net["potential"])
    assert D(net["on_table_year"]) == D(net["on_table"]) * 12
    trend = net["trend"]
    points = [D(v) for v in trend["on_table"]]
    assert D(trend["change"]) == points[-1] - points[0]
    assert trend["span"] and trend["answer"].split(".")[0] in ("Да", "Нет", "Пока нет")

    week = client.get("/api/overview/restaurants/R01", headers=director).json()
    assert D(week["on_table"]) == sum(
        (
            D(f["effect_rub_month"] or 0)
            for f in client.get("/api/findings", headers=director).json()
            if f["status"] not in ("resolved", "dismissed")
        ),
        D(0),
    )

    report = client.get("/api/reports/head", headers=hq, params={"preset": "13w"}).json()
    for name in ("found", "in_work", "confirmed"):
        assert D(report[f"{name}_rub_year"]) == D(report[f"{name}_rub_month"]) * 12, name
    assert report["trend_answer"].startswith(f"За {report['trend']['span']} найденный потенциал")
    for f in client.get("/api/findings", headers=hq).json():
        expected = None if f["effect_rub_month"] is None else D(f["effect_rub_month"]) * 12
        assert (None if f["effect_rub_year"] is None else D(f["effect_rub_year"])) == expected, f["title"]


def test_a_director_gets_an_m3_finding_without_other_restaurants_prices(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    """TC-ISO-12 through the API (code review 27.10.2026, backend 1): the overpay finding of R02 shows its
    director their price and the network's, never the prices of the other restaurants by name."""
    hq = login(client, "admin@a.ru")
    findings = client.get("/api/findings", headers=hq).json()
    findings += client.get("/api/findings", headers=hq, params={"review": "pending"}).json()
    beef = next(f for f in findings if f["title"].startswith("Закупка у дорогого поставщика"))
    if beef["review_status"] == "pending":
        client.post(f"/api/findings/{beef['id']}/review", headers=hq, json={"verdict": "confirm"})
    with Session(owner_engine) as s, s.begin():
        user = User(
            tenant_id=network.a.id, email="r02@a.ru", full_name="R02", password_hash=hash_password(PASSWORD)
        )
        s.add(user)
        s.flush()
        s.add(
            RoleAssignment(
                tenant_id=network.a.id,
                user_id=user.id,
                role=Role.RESTAURANT_DIRECTOR,
                restaurant_id=beef["restaurant_id"],
            )
        )
    director = login(client, "r02@a.ru")
    as_hq = client.get(f"/api/findings/{beef['id']}", headers=hq).json()["view"]
    assert len(as_hq["table"]["rows"]) > 1  # HQ compares the restaurants
    others = [row[0] for row in as_hq["table"]["rows"] if row[0] != beef["restaurant_name"]]
    assert others and len(others) == len(as_hq["table"]["rows"]) - 1
    as_director = client.get(f"/api/findings/{beef['id']}", headers=director).json()["view"]
    assert as_director.get("table") is None and as_director["scale"]["network"] is not None
    listed = next(f for f in client.get("/api/findings", headers=director).json() if f["id"] == beef["id"])
    board = client.get("/api/overview/findings", headers=director).json()
    on_board = next(f for g in board["groups"] for f in g["items"] if f["id"] == beef["id"])
    for shown in (as_director, listed["view"], on_board["view"]):
        assert not any(name in str(shown) for name in others), others


def test_since_the_last_count_and_the_quarter_in_the_picker_and_the_report(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    """Q11 (27.10.2026): «прошлый квартал» and «с последней инвентаризации»; each viewer's own count days."""
    hq, director, foreign = (
        login(client, "admin@a.ru"),
        login(client, "r01@a.ru"),
        login(client, "admin@b.ru"),
    )
    query = (
        "SELECT min(last) FROM (SELECT max(day) AS last FROM inventory_counts "
        "WHERE tenant_id = :t AND day <= DATE '2026-10-18' {only} GROUP BY restaurant_id) x"
    )
    with owner_engine.connect() as c:
        network_last = c.execute(text(query.format(only="")), {"t": network.a.id}).scalar_one()
        r01_last = c.execute(
            text(query.format(only="AND restaurant_id = :r")), {"t": network.a.id, "r": demo["R01"]}
        ).scalar_one()
    assert network_last is not None and r01_last is not None

    def picker(headers: dict[str, str]) -> dict[str, tuple[str, str]]:
        periods = client.get("/api/overview/context", headers=headers).json()["periods"]
        return {p["preset"]: (p["date_from"], p["date_to"]) for p in periods}

    since = (str(network_last + timedelta(days=1)), "2026-10-19")  # to yesterday (today is 20.10)
    assert picker(hq)["since_count"] == since
    assert picker(hq)["quarter"] == ("2026-07-01", "2026-09-30")
    # A director counts from their own restaurant's last count; another network has no counts at all.
    assert picker(director)["since_count"] == (str(r01_last + timedelta(days=1)), "2026-10-19")
    assert "since_count" not in picker(foreign) and "quarter" in picker(foreign)

    report = client.get("/api/reports/head", headers=hq, params={"preset": "since_count"}).json()
    assert (report["date_from"], report["date_to"]) == since
    assert client.get("/api/overview/network", headers=hq, params={"preset": "quarter"}).status_code == 200
    missing = client.get("/api/reports/head", headers=foreign, params={"preset": "since_count"})
    assert missing.status_code == 422 and "Инвентаризаций еще не было" in missing.json()["detail"]


def test_where_the_figures_come_from_down_to_the_invoice(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    """Stage 4: «Откуда цифры» — the loaded rows behind a finding, with their file; the card's rules."""
    hq, director, foreign = (
        login(client, "admin@a.ru"),
        login(client, "r01@a.ru"),
        login(client, "admin@b.ru"),
    )
    with owner_engine.connect() as c:
        ids: dict[str, UUID] = dict(
            c.execute(text("SELECT key, id FROM findings WHERE tenant_id = :t"), {"t": network.a.id}).all()
        )
        r01 = c.execute(text("SELECT name FROM restaurants WHERE id = :r"), {"r": demo["R01"]}).scalar_one()

    def sources(key: str, headers: dict[str, str]) -> httpx.Response:
        response: httpx.Response = client.get(f"/api/findings/{ids[key]}/sources", headers=headers)
        return response

    # A supplier's price: the invoices, with number, supplier, price and the file they came from.
    price = sources("M3:R02:P08", hq).json()
    (invoices,) = price["groups"]
    assert invoices["kind"] == "receipts" and invoices["total"] == len(invoices["rows"]) > 0
    row = invoices["rows"][0]
    assert row["doc_no"] and row["file"].endswith(".csv")
    # One product, one restaurant, one supplier: said once, not repeated on every line.
    assert {"Говядина вырезка", "Мясной экспресс"} <= set(invoices["same"])
    assert "product" not in {c["key"] for c in invoices["columns"]}
    assert row["unit"] == "кг"
    # A network-wide finding: every restaurant's invoices, for HQ.
    growth = sources("M3:net:P09:growth", hq).json()
    assert len({r["restaurant"] for r in growth["groups"][0]["rows"]}) > 1

    # The director: their restaurant's finding shows only their restaurant's rows, opening count included.
    own = sources("M1:R01:P01", director).json()
    kinds = {g["kind"]: g for g in own["groups"]}
    assert all(r["restaurant"] == r01 for g in own["groups"] for r in g["rows"])
    assert len(kinds["counts"]["rows"]) == 2  # the counts that open and close the period
    # Another restaurant's finding, a network-wide one, another network: not found.
    assert sources("M3:R02:P08", director).status_code == 404
    assert sources("M3:net:P09:growth", director).status_code == 404
    assert sources("M3:R02:P08", foreign).status_code == 404
    # A skipped count: the counts the restaurant did make.
    overdue = sources("M4:R08:overdue", hq).json()
    assert [g["kind"] for g in overdue["groups"]] == ["counts"]
    # A finding about what was never loaded: no documents, and it says so.
    with get_sessionmaker()() as session:
        load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        gap = Finding(
            tenant_id=network.a.id,
            restaurant_id=demo["R01"],
            module="M7",
            kind="problem",
            process="accounting",
            title="Нет выгрузки",
            headline="h",
            status="new",
            found_on=date(2026, 10, 20),
            evidence={"kind": "gap", "source": "receipts", "last": "2025-01-01"},
        )
        session.add(gap)
        session.commit()
        gap_id = gap.id
    missing = client.get(f"/api/findings/{gap_id}/sources", headers=hq).json()
    assert missing["groups"] == [] and "Документов нет" in missing["note"]


def test_restaurants_by_processes_and_the_networks_figures(
    client: TestClient, network: Network, demo: dict[str, UUID]
) -> None:
    """Stage 4 (docs/10, 4.3): «Сеть» shows restaurants × processes in ₽ and the network's own figures."""
    hq = login(client, "admin@a.ru")
    net = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()
    processes = [p["process"] for p in net["processes"]]
    assert processes[0] == "purchasing" and len(processes) == 8
    # Each cell: the open checked problems of that restaurant and process, summed from the list itself.
    findings = client.get("/api/findings", headers=hq).json()
    places = {r["id"]: r["code"] for r in client.get("/api/restaurants", headers=hq).json()}
    expected: dict[tuple[str, str], Decimal] = {}
    for f in findings:
        if f["kind"] == "problem" and f["status"] != "resolved" and f["restaurant_id"]:
            key = (places[f["restaurant_id"]], f["process"])
            expected[key] = expected.get(key, Decimal(0)) + Decimal(f["effect_rub_month"] or 0)
    for row in net["matrix"]:
        assert [c["process"] for c in row["cells"]] == processes
        for c in row["cells"]:
            assert Decimal(c["losses"]) == expected.get((row["code"], c["process"]), Decimal(0))
            assert (c["status"] == "good") == (c["count"] == 0)
        assert Decimal(row["total"]) == sum(Decimal(c["losses"]) for c in row["cells"])
    by_process: dict[str, Decimal] = {}
    for (_, process), losses in expected.items():
        by_process[process] = by_process.get(process, Decimal(0)) + losses
    top = next(
        p["title"] for p in net["processes"] if p["process"] == max(by_process, key=by_process.__getitem__)
    )
    assert net["matrix_answer"].startswith(f"Больше всего теряем на процессе «{top}»")
    totals = [Decimal(r["total"]) for r in net["matrix"]]
    assert totals == sorted(totals, reverse=True)
    # The network's figures: food cost and write-offs from the engine, overpayment from purchasing problems.
    assert net["kpi"] and Decimal(net["kpi"]["food_cost_actual"]) > 0
    overpay = sum(
        (
            Decimal(f["effect_rub_month"] or 0)
            for f in findings
            if f["kind"] == "problem" and f["status"] != "resolved" and f["process"] == "purchasing"
        ),
        Decimal(0),
    )
    assert Decimal(net["overpay"]) == overpay > 0


def test_documents_after_the_stage_4_review(
    client: TestClient, network: Network, demo: dict[str, UUID], owner_engine: Engine
) -> None:
    """Code review 27.10.2026 (stage 4): an incoming transfer is shown to the receiving director without the
    sender's name or file; a product no longer in the catalogue gives no rows (not all the rows)."""
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    with owner_engine.begin() as c:
        finding = c.execute(
            text("SELECT id, period_from FROM findings WHERE tenant_id = :t AND key = 'M1:R01:P01'"),
            {"t": network.a.id},
        ).one()
        r02, batch, product = c.execute(
            text(
                "SELECT r.id, b.id, p.id FROM restaurants r JOIN import_batches b ON b.restaurant_id = r.id "
                "JOIN products p ON p.tenant_id = r.tenant_id AND p.code = 'P01' "
                "WHERE r.tenant_id = :t AND r.code = 'R02' LIMIT 1"
            ),
            {"t": network.a.id},
        ).one()
        c.execute(
            text(
                "INSERT INTO transfers (id, tenant_id, restaurant_id, to_restaurant_id, import_batch_id, "
                "day, product_id, qty) VALUES (gen_random_uuid(), :t, :src, :dst, :b, :d, :p, 2.5)"
            ),
            {
                "t": network.a.id,
                "src": r02,
                "dst": demo["R01"],
                "b": batch,
                "d": finding.period_from,
                "p": product,
            },
        )
    groups = {
        g["kind"]: g
        for g in client.get(f"/api/findings/{finding.id}/sources", headers=director).json()["groups"]
    }
    (incoming,) = groups["transfers"]["rows"]
    assert incoming["route"].startswith("другой ресторан сети → ") and incoming["file"] is None
    assert groups["transfers"]["total"] == 1
    # HQ sees both restaurants by name and the sender's file.
    hq_groups = {
        g["kind"]: g for g in client.get(f"/api/findings/{finding.id}/sources", headers=hq).json()["groups"]
    }
    assert hq_groups["transfers"]["rows"][0]["file"]

    with owner_engine.begin() as c:
        c.execute(
            text('UPDATE findings SET evidence = evidence || \'{"product": "NO-SUCH"}\' WHERE id = :f'),
            {"f": finding.id},
        )
    gone = client.get(f"/api/findings/{finding.id}/sources", headers=hq).json()
    assert gone["groups"] == []
