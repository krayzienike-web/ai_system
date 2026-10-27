"""Findings → tasks → checks → result, through the API: roles, rules and isolation (ADR 0006)."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.errors import InvalidError
from app.core.period import get_today
from app.experiments.models import Experiment, Verdict
from app.experiments.service import record_result
from app.insights.models import Finding
from app.main import app
from app.tasks.models import OutcomeVerdict, Task
from app.tasks.service import record_outcome
from tests.conftest import Network, login

TODAY = date(2026, 10, 23)


@dataclass
class Work:
    mozzarella: UUID  # A1, has a running check
    beef: UUID  # A2, has a proposed check
    fries: UUID  # network-wide (HQ only)
    foreign: UUID  # tenant B
    beef_check: UUID
    late_task: UUID  # A2, overdue


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


@pytest.fixture
def work(owner_engine: Engine, network: Network) -> Work:
    a, b = network.a, network.b
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():

        def finding(
            tenant: UUID, restaurant: UUID | None, title: str, effect: str | None, found: date
        ) -> Finding:
            f = Finding(
                tenant_id=tenant,
                restaurant_id=restaurant,
                kind="problem",
                process="production",
                title=title,
                effect_rub_month=Decimal(effect) if effect else None,
                actions=["Шаг 1", "Шаг 2"],
                found_on=found,
            )
            s.add(f)
            s.flush()
            return f

        moz = finding(a.id, a.restaurants["A1"], "Перерасход моцареллы", "38000.00", date(2026, 10, 1))
        beef = finding(a.id, a.restaurants["A2"], "Говядина дороже сети", "31000.00", date(2026, 10, 1))
        fries = finding(a.id, None, "ТТК фри устарела", None, date(2026, 10, 1))
        greens = finding(a.id, a.restaurants["A3"], "Зелень списывается", "5200.00", date(2026, 9, 1))
        greens.status, greens.resolved_on = "resolved", date(2026, 10, 10)
        foreign = finding(b.id, b.restaurants["B1"], "Чужая находка", "1000.00", date(2026, 10, 1))
        moz.status = "in_experiment"

        running = Experiment(
            tenant_id=a.id,
            finding_id=moz.id,
            title="Взвешивание сыра",
            hypothesis="…",
            metric="перерасход, %",
            test_restaurant_ids=[a.restaurants["A1"]],
            starts_on=date(2026, 10, 13),
            ends_on=date(2026, 11, 10),
            expected_rub_month=Decimal("25500.00"),
            status="running",
        )
        proposed = Experiment(
            tenant_id=a.id,
            finding_id=beef.id,
            title="Плановый заказ говядины",
            hypothesis="…",
            metric="цена, ₽/кг",
            test_restaurant_ids=[a.restaurants["A2"]],
            control_restaurant_ids=[a.restaurants["A1"], a.restaurants["A3"]],
            starts_on=date(2026, 10, 27),
            ends_on=date(2026, 11, 24),
            expected_rub_month=Decimal("18600.00"),
        )
        failed = Experiment(
            tenant_id=a.id,
            title="Дозаторы для соусов",
            hypothesis="…",
            metric="соусы сверх ТТК",
            test_restaurant_ids=[a.restaurants["A2"]],
            starts_on=date(2026, 9, 8),
            ends_on=date(2026, 10, 5),
            expected_rub_month=Decimal("6000.00"),
            status="completed",
            verdict="rejected",
            effect_rub_month=Decimal(0),
            result_text="Расход соусов не изменился",
            completed_on=date(2026, 10, 5),
        )
        confirmed = Experiment(
            tenant_id=a.id,
            finding_id=greens.id,
            title="Малые партии зелени",
            hypothesis="…",
            metric="списания",
            test_restaurant_ids=[a.restaurants["A3"]],
            starts_on=date(2026, 9, 15),
            ends_on=date(2026, 10, 10),
            expected_rub_month=Decimal("4000.00"),
            status="completed",
            verdict="confirmed",
            effect_rub_month=Decimal("5200.00"),
            result_text="−48% списаний",
            completed_on=date(2026, 10, 10),
        )
        s.add_all([running, proposed, failed, confirmed])
        s.flush()
        common = {"tenant_id": a.id, "assigned_by": "hq"}
        late = Task(
            **common,
            restaurant_id=a.restaurants["A2"],
            title="Взвешивать поставки",
            created_on=date(2026, 10, 14),
            due_on=date(2026, 10, 20),
        )
        s.add_all(
            [
                late,
                Task(
                    **common,
                    restaurant_id=a.restaurants["A1"],
                    finding_id=moz.id,
                    experiment_id=running.id,
                    title="Взвешивание сыра",
                    created_on=date(2026, 10, 13),
                    due_on=date(2026, 11, 10),
                    status="in_progress",
                ),
                Task(
                    **common,
                    restaurant_id=a.restaurants["A3"],
                    finding_id=greens.id,
                    experiment_id=confirmed.id,
                    title="Малые партии зелени",
                    created_on=date(2026, 9, 15),
                    due_on=date(2026, 10, 10),
                    status="done",
                    done_on=date(2026, 10, 10),
                    report="Заказ на вторник и пятницу",
                    outcome_verdict="confirmed",
                ),
            ]
        )
    return Work(moz.id, beef.id, fries.id, foreign.id, proposed.id, late.id)


def _titles(rows: list[dict[str, object]]) -> set[object]:
    return {r["title"] for r in rows}


# ------------------------------------------------------------------ isolation


def test_director_sees_only_own_findings_and_no_network_wide(client: TestClient, work: Work) -> None:
    headers = login(client, "director1@a.ru")
    assert _titles(client.get("/api/findings", headers=headers).json()) == {"Перерасход моцареллы"}
    for other in (work.beef, work.fries, work.foreign):
        assert client.get(f"/api/findings/{other}", headers=headers).status_code == 404


def test_hq_sees_all_findings_of_own_tenant_only(client: TestClient, work: Work) -> None:
    titles = _titles(client.get("/api/findings", headers=login(client, "admin@a.ru")).json())
    assert titles == {
        "Перерасход моцареллы",
        "Говядина дороже сети",
        "ТТК фри устарела",
        "Зелень списывается",
    }
    assert client.get(f"/api/findings/{work.foreign}", headers=login(client, "admin@a.ru")).status_code == 404
    assert _titles(client.get("/api/findings", headers=login(client, "admin@b.ru")).json()) == {
        "Чужая находка"
    }


def test_director_sees_only_own_tasks(client: TestClient, work: Work) -> None:
    assert _titles(client.get("/api/tasks", headers=login(client, "director2@a.ru")).json()) == {
        "Взвешивать поставки"
    }
    assert client.get("/api/tasks", headers=login(client, "admin@b.ru")).json() == []


def test_checks_and_head_report_are_hq_only(client: TestClient, work: Work) -> None:
    director = login(client, "director1@a.ru")
    assert client.get("/api/checks", headers=director).status_code == 403
    assert client.post(f"/api/checks/{work.beef_check}/launch", headers=director).status_code == 403
    assert client.get("/api/reports/head", headers=director).status_code == 403
    # The finding card shows a director the work but not the check itself.
    card = client.get(f"/api/findings/{work.mozzarella}", headers=director).json()
    assert card["check"] is None
    assert [t["title"] for t in card["tasks"]] == ["Взвешивание сыра"]


def test_other_tenant_cannot_touch_checks_or_tasks(client: TestClient, work: Work) -> None:
    headers = login(client, "admin@b.ru")
    assert client.post(f"/api/checks/{work.beef_check}/launch", headers=headers).status_code == 404
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete", headers=headers, json={"report": "x"}
        ).status_code
        == 403
    )
    director_b = login(client, "director1@b.ru")
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete", headers=director_b, json={"report": "x"}
        ).status_code
        == 404
    )


# ------------------------------------------------------------------ work stage on findings


def test_findings_carry_work_stage(client: TestClient, work: Work) -> None:
    rows = {r["title"]: r for r in client.get("/api/findings", headers=login(client, "admin@a.ru")).json()}
    assert rows["Перерасход моцареллы"]["work"]["stage"] == "checking"
    assert rows["Говядина дороже сети"]["work"]["stage"] == "new"
    assert rows["Говядина дороже сети"]["work"]["check_waiting_launch"] is True
    assert rows["Зелень списывается"]["work"]["stage"] == "done"
    assert Decimal(rows["Зелень списывается"]["work"]["confirmed_rub_month"]) == Decimal("5200.00")
    # Money first, findings without an estimate last.
    assert list(rows)[-1] == "ТТК фри устарела"


def test_stage_filter(client: TestClient, work: Work) -> None:
    headers = login(client, "admin@a.ru")
    assert _titles(client.get("/api/findings", params={"stage": "checking"}, headers=headers).json()) == {
        "Перерасход моцареллы"
    }
    assert client.get("/api/findings", params={"stage": "later"}, headers=headers).status_code == 422


# ------------------------------------------------------------------ quick tasks


def test_hq_assigns_a_step_to_the_director_and_finding_moves_to_doing(client: TestClient, work: Work) -> None:
    hq = login(client, "admin@a.ru")
    r = client.post(
        "/api/tasks",
        headers=hq,
        json={"title": "Шаг 1", "finding_id": str(work.beef), "due_on": "2026-10-30"},
    )
    assert r.status_code == 201, r.text
    [task] = r.json()
    assert task["assigned_by"] == "hq" and task["created_on"] == "2026-10-23" and task["status"] == "assigned"
    card = client.get(f"/api/findings/{work.beef}", headers=hq).json()
    assert card["status"] == "in_work" and card["work"]["stage"] == "doing"
    assert "Шаг 1" in _titles(client.get("/api/tasks", headers=login(client, "director2@a.ru")).json())


def test_network_wide_finding_goes_to_every_director(
    client: TestClient, work: Work, network: Network
) -> None:
    r = client.post(
        "/api/tasks",
        headers=login(client, "admin@a.ru"),
        json={"title": "Обновить ТТК фри", "finding_id": str(work.fries), "due_on": "2026-10-30"},
    )
    assert {t["restaurant_id"] for t in r.json()} == {str(v) for v in network.a.restaurants.values()}


def test_finding_of_one_restaurant_cannot_go_to_another(
    client: TestClient, work: Work, network: Network
) -> None:
    r = client.post(
        "/api/tasks",
        headers=login(client, "admin@a.ru"),
        json={
            "title": "Шаг",
            "finding_id": str(work.beef),
            "due_on": "2026-10-30",
            "restaurant_ids": [str(network.a.restaurants["A1"])],
        },
    )
    assert r.status_code == 422


def test_director_takes_own_step_but_not_for_others(client: TestClient, work: Work, network: Network) -> None:
    director = login(client, "director1@a.ru")
    own = client.post(
        "/api/tasks",
        headers=director,
        json={"title": "Шаг", "finding_id": str(work.mozzarella), "due_on": "2026-10-30"},
    )
    assert own.status_code == 201 and own.json()[0]["assigned_by"] == "director"
    other_finding = client.post(
        "/api/tasks",
        headers=director,
        json={"title": "Шаг", "finding_id": str(work.beef), "due_on": "2026-10-30"},
    )
    assert other_finding.status_code == 404
    other_restaurant = client.post(
        "/api/tasks",
        headers=director,
        json={"title": "Шаг", "due_on": "2026-10-30", "restaurant_ids": [str(network.a.restaurants["A2"])]},
    )
    assert other_restaurant.status_code == 403


def test_analyst_cannot_assign(client: TestClient, work: Work) -> None:
    r = client.post(
        "/api/tasks",
        headers=login(client, "analyst@a.ru"),
        json={"title": "Шаг", "finding_id": str(work.beef), "due_on": "2026-10-30"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize("due", ["2026-10-22", "2027-02-01"])
def test_due_date_must_be_reasonable(client: TestClient, work: Work, due: str) -> None:
    r = client.post(
        "/api/tasks",
        headers=login(client, "admin@a.ru"),
        json={"title": "Шаг", "finding_id": str(work.beef), "due_on": due},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ execution and report


def test_director_completes_with_report_and_result_is_pending(client: TestClient, work: Work) -> None:
    director = login(client, "director2@a.ru")
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete", headers=director, json={"report": "  "}
        ).status_code
        == 422
    )
    r = client.post(f"/api/tasks/{work.late_task}/complete", headers=director, json={"report": "Весы стоят"})
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["done_on"], body["report"], body["late"]) == (
        "done",
        "2026-10-23",
        "Весы стоят",
        False,
    )
    assert body["outcome"] == {
        "verdict": "pending",
        "effect_rub_month": None,
        "text": None,
        "measured_on": None,
    }
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete", headers=director, json={"report": "ещё"}
        ).status_code
        == 422
    )


def test_hq_does_not_execute_and_director_cannot_complete_others(client: TestClient, work: Work) -> None:
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete", headers=login(client, "admin@a.ru"), json={"report": "x"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/tasks/{work.late_task}/complete",
            headers=login(client, "director1@a.ru"),
            json={"report": "x"},
        ).status_code
        == 404
    )


def test_no_endpoint_lets_a_person_write_a_result(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "outcome" in p or "result" in p]


def test_launch_sets_tasks_for_test_restaurants(client: TestClient, work: Work) -> None:
    hq = login(client, "admin@a.ru")
    r = client.post(f"/api/checks/{work.beef_check}/launch", headers=hq)
    assert r.status_code == 200
    [task] = r.json()
    assert (task["title"], task["due_on"], task["assigned_by"]) == (
        "Плановый заказ говядины",
        "2026-11-24",
        "hq",
    )
    assert client.get(f"/api/findings/{work.beef}", headers=hq).json()["status"] == "in_experiment"
    assert client.post(f"/api/checks/{work.beef_check}/launch", headers=hq).status_code == 422
    assert "Плановый заказ говядины" in _titles(
        client.get("/api/tasks", headers=login(client, "director2@a.ru")).json()
    )


def test_reject_proposal(client: TestClient, work: Work) -> None:
    hq = login(client, "admin@a.ru")
    assert client.post(f"/api/checks/{work.beef_check}/reject", headers=hq).json()["status"] == "rejected"
    assert client.get("/api/checks", params={"status": "proposed"}, headers=hq).json() == []


def test_head_report_numbers_and_failures(client: TestClient, work: Work) -> None:
    r = client.get("/api/reports/head", params={"preset": "4w"}, headers=login(client, "admin@a.ru")).json()
    assert (r["date_from"], r["date_to"]) == ("2026-09-21", "2026-10-18")
    assert Decimal(r["found_rub_month"]) == Decimal("69000.00")  # open: mozzarella + beef
    assert Decimal(r["in_work_rub_month"]) == Decimal("38000.00")  # mozzarella is being checked
    assert Decimal(r["confirmed_rub_month"]) == Decimal("5200.00")  # from the check, not doubled by its task
    # Before the period only the greens were open; by its end they are closed and three others are open.
    assert (r["open_findings_before"], r["open_findings_now"], r["closed_findings"]) == (1, 3, 1)
    assert Decimal(r["potential_before_rub_month"]) == Decimal("5200.00")
    assert Decimal(r["potential_now_rub_month"]) == Decimal("69000.00")
    assert [t["title"] for t in r["done_tasks"]] == ["Малые партии зелени"]
    assert [(f["kind"], f["title"]) for f in r["failures"]] == [("check_no_effect", "Дозаторы для соусов")]


def test_head_report_period_excludes_earlier_events(client: TestClient, work: Work) -> None:
    hq = login(client, "admin@a.ru")
    week = client.get("/api/reports/head", params={"preset": "week"}, headers=hq).json()
    assert week["done_tasks"] == [] and week["closed_findings"] == 0
    # Due 20.10: not overdue yet at the end of the week of 12–18.10, overdue in a period that covers 20.10.
    assert week["failures"] == []
    later = client.get(
        "/api/reports/head", params={"date_from": "2026-10-19", "date_to": "2026-10-22"}, headers=hq
    ).json()
    assert [f["kind"] for f in later["failures"]] == ["task_overdue"]


# ------------------------------------------------------------------ results are written by analytics only


def test_outcome_rules(owner_engine: Engine, work: Work) -> None:
    with Session(owner_engine) as s, s.begin():
        task = s.get(Task, work.late_task)
        assert task is not None
        with pytest.raises(InvalidError):
            record_outcome(
                s,
                task,
                verdict=OutcomeVerdict.CONFIRMED,
                text="",
                measured_on=TODAY,
                effect_rub_month=Decimal(1),
            )
        task.status, task.done_on, task.report = "done", TODAY, "ok"
        with pytest.raises(InvalidError):
            record_outcome(
                s,
                task,
                verdict=OutcomeVerdict.CONFIRMED,
                text="",
                measured_on=TODAY,
                effect_rub_month=Decimal(0),
            )
        record_outcome(
            s,
            task,
            verdict=OutcomeVerdict.CONFIRMED,
            text="−2%",
            measured_on=TODAY,
            effect_rub_month=Decimal("900.00"),
        )
        assert task.outcome_effect_rub_month == Decimal("900.00")


def test_check_result_reaches_its_done_tasks(owner_engine: Engine, work: Work) -> None:
    with Session(owner_engine) as s, s.begin():
        exp = s.execute(select(Experiment).where(Experiment.title == "Взвешивание сыра")).scalar_one()
        task = s.execute(select(Task).where(Task.experiment_id == exp.id)).scalar_one()
        task.status, task.done_on, task.report = "done", TODAY, "ok"
        with pytest.raises(InvalidError):
            record_result(
                s,
                exp,
                verdict=Verdict.CONFIRMED,
                effect_rub_month=Decimal(10),
                ci_low=Decimal(20),
                ci_high=Decimal(30),
                text="",
                completed_on=TODAY,
            )
        record_result(
            s,
            exp,
            verdict=Verdict.REJECTED,
            effect_rub_month=Decimal(0),
            ci_low=Decimal(-5),
            ci_high=Decimal(5),
            text="Нет эффекта",
            completed_on=TODAY,
        )
        assert (task.outcome_verdict, task.outcome_text, task.outcome_effect_rub_month) == (
            "not_confirmed",
            "Нет эффекта",
            None,
        )


def test_work_actions_on_another_restaurant_or_network_are_not_found(
    client: TestClient, work: Work, network: Network
) -> None:
    """TC-ISO-13 (CLAUDE.md, principle 2): every work endpoint that takes an id treats a task, check or
    finding of another restaurant or network as missing (404) and changes nothing."""
    hq_b, director_b = login(client, "admin@b.ru"), login(client, "director1@b.ru")
    director_a1 = login(client, "director1@a.ru")
    # Tasks: A2's overdue task — A1's director and network B's director cannot start or tick it.
    for stranger in (director_a1, director_b):
        assert client.post(f"/api/tasks/{work.late_task}/start", headers=stranger).status_code == 404
        tick = client.post(
            f"/api/tasks/{work.late_task}/checklist", headers=stranger, json={"index": 0, "done": True}
        )
        assert tick.status_code == 404
    # A task about another network's finding cannot be set, nor one about another restaurant's.
    due = "2026-10-30"
    for headers, finding in ((hq_b, work.beef), (director_a1, work.beef)):
        made = client.post(
            "/api/tasks", headers=headers, json={"title": "Шаг", "finding_id": str(finding), "due_on": due}
        )
        assert made.status_code == 404, made.text
    # Checks of network A: network B's admin cannot draft, propose, open, launch or reject them.
    assert client.get("/api/checks", headers=hq_b).json() == []
    assert (
        client.get("/api/checks/draft", headers=hq_b, params={"finding_id": str(work.beef)}).status_code
        == 404
    )
    proposal = {"finding_id": str(work.beef), "action": "Шаг 1", "control_ids": [], "weeks": 4}
    assert client.post("/api/checks", headers=hq_b, json=proposal).status_code == 404
    for path in (f"/api/checks/{work.beef_check}/launch", f"/api/checks/{work.beef_check}/reject"):
        assert client.post(path, headers=hq_b).status_code == 404, path
    # Network A's checks and tasks are as they were.
    hq_a = login(client, "admin@a.ru")
    beef_check = client.get(f"/api/checks/{work.beef_check}", headers=hq_a).json()
    assert beef_check["status"] == "proposed"
    late = next(t for t in client.get("/api/tasks", headers=hq_a).json() if t["id"] == str(work.late_task))
    assert late["status"] == "assigned"
    # The head report and the badges of network B count nothing of network A.
    report = client.get("/api/reports/head", headers=hq_b, params={"preset": "13w"}).json()
    assert (
        report["checks"] == []
        and report["done_tasks"] == []
        and Decimal(report["found_rub_month"]) == Decimal("1000.00")
    )  # «Чужая находка» of B1 is network B's only finding
    assert client.get("/api/overview/badges", headers=hq_b).json()["open_tasks"] == 0
