"""Overview screens, actions and chat on the server (ADR 0007): figures, access rules, isolation."""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
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
    assert ctx == {"today": "2026-10-20", "data_until": "2026-10-18", "next_count_on": "2026-11-29"}

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
    assert client.get(f"/api/checks/{proposed['id']}", headers=foreign).status_code == 404

    checks = client.get("/api/checks", headers=hq).json()
    worked = next(c for c in checks if c["verdict"] == "confirmed")
    detail = client.get(f"/api/checks/{worked['id']}", headers=hq).json()
    assert detail["tasks"][0]["outcome"]["verdict"] == "confirmed"
    assert client.post(f"/api/checks/{worked['id']}/rollout", headers=analyst).status_code == 403
    tasks = client.post(f"/api/checks/{worked['id']}/rollout", headers=hq).json()
    assert len(tasks) == 14 and "R01" not in {t["restaurant_code"] for t in tasks}  # R01 already did it
    assert client.post(f"/api/checks/{worked['id']}/rollout", headers=hq).status_code == 422
    unclear = next(c for c in checks if c["verdict"] == "inconclusive")
    assert client.post(f"/api/checks/{unclear['id']}/rollout", headers=hq).status_code == 422


def test_head_report_and_chat(client: TestClient, network: Network, demo: dict[str, UUID]) -> None:
    hq, director = login(client, "admin@a.ru"), login(client, "r01@a.ru")
    report = client.get("/api/reports/head", headers=hq, params={"preset": "13w"}).json()
    assert report["network_name"] == "Сеть А" and len(report["checks"]) == 4
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
