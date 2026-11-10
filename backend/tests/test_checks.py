"""Checks of changes before stage 7 (docs/05, steps 2–5 and 7): the draft, the proposal, launch and reject,
roll-out, the result written by the measurement only, the «Сэкономлено» counter, roles and isolation.

The measurement itself (difference in differences, bootstrap, verdicts, designs B and C) does not exist yet:
its test plan is in docs/13, «Пробелы и план», TC-EXP-20…"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.core.errors import InvalidError
from app.core.period import get_today
from app.core.security import hash_password
from app.experiments.models import Experiment, Verdict
from app.experiments.service import record_result
from app.insights.models import Finding
from app.main import app
from app.overview.models import KpiSnapshot
from app.tasks.models import Task
from app.tenancy.models import AuditLog, Restaurant, Role, RoleAssignment, User
from tests.conftest import PASSWORD, Network, login

D = Decimal
TODAY = date(2026, 10, 23)  # a Friday


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


@dataclass
class Place:
    r: dict[str, UUID]  # code -> restaurant id, network A (A1…A5)
    cheese: UUID  # A1's finding, 38 100 ₽ a month, measured against the network
    pending: UUID  # A2's engine finding still waiting for the review
    foreign_finding: UUID  # network B's finding
    worked: UUID  # A3's completed confirmed check with a done task
    unclear: UUID  # A2's completed inconclusive check
    foreign_check: UUID  # network B's confirmed check


@pytest.fixture
def place(owner_engine: Engine, network: Network) -> Place:
    """Network A gets two more restaurants (A4 with a director, A5 without revenue) so the three most similar
    can be chosen from four; network B has a restaurant with exactly A1's revenue that must never show up."""
    a, b = network.a, network.b
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        for i, code in ((4, "A4"), (5, "A5")):
            rest = Restaurant(tenant_id=a.id, code=code, name=f"Сеть А {code}")
            s.add(rest)
            s.flush()
            a.restaurants[code] = rest.id
            user = User(
                tenant_id=a.id,
                email=f"director{i}@a.ru",
                full_name=code,
                password_hash=hash_password(PASSWORD),
            )
            s.add(user)
            s.flush()
            s.add(
                RoleAssignment(
                    tenant_id=a.id, user_id=user.id, role=Role.RESTAURANT_DIRECTOR, restaurant_id=rest.id
                )
            )
        revenue = {"A1": "1000000.00", "A2": "1100000.00", "A3": "700000.00", "A4": "950000.00"}
        for code, rub in revenue.items():
            s.add(
                KpiSnapshot(
                    tenant_id=a.id, restaurant_id=a.restaurants[code], computed_on=TODAY, revenue=D(rub)
                )
            )
        s.add(KpiSnapshot(tenant_id=a.id, restaurant_id=None, computed_on=TODAY, revenue=D("3750000.00")))
        s.add(
            KpiSnapshot(
                tenant_id=b.id, restaurant_id=b.restaurants["B1"], computed_on=TODAY, revenue=D("1000000.00")
            )
        )

        def finding(tenant: UUID, restaurant: UUID, title: str, **kw: object) -> Finding:
            # an overuse finding of a product (M1): the measurement has a metric for it (stage 7)
            if not s.execute(
                select(Product).where(Product.tenant_id == tenant, Product.code == "P01")
            ).first():
                s.add(
                    Product(
                        tenant_id=tenant, code="P01", name="Сыр Моцарелла", category="Сыры", base_unit="kg"
                    )
                )
            f = Finding(
                tenant_id=tenant,
                restaurant_id=restaurant,
                kind="problem",
                process="production",
                title=title,
                actions=["Взвешивать сыр на раздаче", "Обучить по ТТК"],
                found_on=date(2026, 10, 1),
                module="M1",
                evidence={"product": "P01"},
                **kw,
            )
            s.add(f)
            s.flush()
            return f

        cheese = finding(
            a.id,
            a.restaurants["A1"],
            "Перерасход моцареллы",
            effect_rub_month=D("38100.00"),
            view={
                "scale": {
                    "label": "Перерасход моцареллы, %",
                    "unit": "%",
                    "me": 9.0,
                    "network": 3.0,
                    "lower_is_better": True,
                }
            },
        )
        pending = finding(
            a.id,
            a.restaurants["A2"],
            "Перерасход сливок",
            effect_rub_month=D("9000.00"),
            review_status="pending",
        )
        foreign_finding = finding(b.id, b.restaurants["B1"], "Чужая находка", effect_rub_month=D("1000.00"))

        def check(tenant: UUID, test: UUID, title: str, verdict: str, effect: str) -> Experiment:
            e = Experiment(
                tenant_id=tenant,
                title=title,
                hypothesis="…",
                metric="списания",
                test_restaurant_ids=[test],
                starts_on=date(2026, 9, 1),
                ends_on=date(2026, 9, 29),
                expected_rub_month=D("4000.00"),
                status="completed",
                verdict=verdict,
                effect_rub_month=D(effect),
                result_text="…",
                completed_on=date(2026, 9, 29),
            )
            s.add(e)
            s.flush()
            return e

        worked = check(a.id, a.restaurants["A3"], "Малые партии зелени", "confirmed", "5200.00")
        unclear = check(a.id, a.restaurants["A2"], "Дозаторы для соусов", "inconclusive", "3000.00")
        foreign_check = check(b.id, b.restaurants["B1"], "Чужая проверка", "confirmed", "50000.00")
        s.add(
            Task(
                tenant_id=a.id,
                restaurant_id=a.restaurants["A3"],
                experiment_id=worked.id,
                title=worked.title,
                assigned_by="hq",
                created_on=date(2026, 9, 1),
                due_on=date(2026, 9, 29),
                status="done",
                done_on=date(2026, 9, 29),
                report="Заказ дважды в неделю",
                outcome_verdict="confirmed",
            )
        )
    return Place(
        dict(a.restaurants),
        cheese.id,
        pending.id,
        foreign_finding.id,
        worked.id,
        unclear.id,
        foreign_check.id,
    )


def _propose(client: TestClient, headers: dict[str, str], finding: UUID, **over: object) -> dict[str, object]:
    draft = client.get("/api/checks/draft", headers=headers, params={"finding_id": str(finding)}).json()
    return {
        "finding_id": str(finding),
        "action": draft["actions"][0],
        "control_ids": [c["restaurant_id"] for c in draft["candidates"] if c["suggested"]],
        "weeks": 4,
        **over,
    }


def _audit(owner_engine: Engine, action: str, entity_id: UUID) -> list[AuditLog]:
    with Session(owner_engine) as s:
        return list(
            s.execute(
                select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
            ).scalars()
        )


# ------------------------------------------------------------------ the draft (docs/05, step 3)


def test_the_draft_compares_with_the_three_most_similar_by_revenue_of_its_own_network(
    client: TestClient, place: Place
) -> None:
    """TC-EXP-01. A1 has 1 000 000 ₽; |rev − 1 000 000| / 1 000 000: A4 950 000 → 5 %, A2 1 100 000 → 10 %,
    A3 700 000 → 30 %, A5 no revenue → last. The first three are suggested; the test restaurant itself and
    network B's B1 (exactly the same revenue, distance 0 %) are not candidates at all."""
    analyst = login(client, "analyst@a.ru")
    draft = client.get("/api/checks/draft", headers=analyst, params={"finding_id": str(place.cheese)}).json()
    assert draft["test"]["code"] == "A1"
    assert [(c["code"], c["suggested"], c["reason"]) for c in draft["candidates"]] == [
        ("A4", True, "выручка отличается на 5%"),
        ("A2", True, "выручка отличается на 10%"),
        ("A3", True, "выручка отличается на 30%"),
        ("A5", False, "нет данных о выручке"),
    ]
    assert draft["actions"] == ["Взвешивать сыр на раздаче", "Обучить по ТТК"]
    assert [(d["weeks"]) for d in draft["durations"]] == [2, 4, 6] and draft["default_weeks"] == 4
    # Expected = 60 % of the finding, rounded to 100 ₽: 38 100 × 0,6 = 22 860 → 228,6 hundreds → 229 → 22 900.
    assert D(draft["expected_rub_month"]) == D("22900")
    # The metric and where it should go come from the finding: it has a network level, so «уровню сети».
    assert draft["success"].startswith("«Перерасход моцареллы, %» приблизится к уровню сети. Ожидаем +")
    assert "60% от найденного" in draft["success"]


def test_a_draft_needs_a_checked_finding_of_ones_own_network(client: TestClient, place: Place) -> None:
    """TC-EXP-02. A finding waiting for the review → 422; another network's finding → 404."""
    hq = login(client, "admin@a.ru")
    pending = client.get("/api/checks/draft", headers=hq, params={"finding_id": str(place.pending)})
    assert pending.status_code in (404, 422)
    foreign = client.get("/api/checks/draft", headers=hq, params={"finding_id": str(place.foreign_finding)})
    assert foreign.status_code == 404


# ------------------------------------------------------------------ the proposal (docs/05, steps 2–4)


def test_a_proposal_fixes_dates_text_and_money_and_sets_no_task_yet(
    client: TestClient, place: Place, owner_engine: Engine
) -> None:
    """TC-EXP-03. Today 23.10 (Fri); the director gets 3 days: start 26.10, 4 weeks → end 23.11.
    A person approves consequences (CLAUDE.md, principle 5): a proposal sets no task."""
    analyst = login(client, "analyst@a.ru")
    body = _propose(client, analyst, place.cheese)
    r = client.post("/api/checks", headers=analyst, json=body)
    assert r.status_code == 201, r.text
    check = r.json()
    assert (check["status"], check["starts_on"], check["ends_on"], check["weeks"]) == (
        "proposed",
        "2026-10-26",
        "2026-11-23",
        4,
    )
    # the template of docs/05 with the chosen measure and length (stage 7 review, frontend p. 8)
    assert check["hypothesis"].startswith("Если в ресторане «")
    assert (
        "» взвешивать сыр на раздаче, «Перерасход моцареллы, %» приблизится к уровню сети за 4 недели"
        in (check["hypothesis"])
    )
    assert check["metric"] == "Перерасход моцареллы, %"
    assert D(check["expected_rub_month"]) == D("22900")
    assert [p["code"] for p in check["test"]] == ["A1"]
    assert [p["code"] for p in check["control"]] == ["A4", "A2", "A3"]
    assert check["verdict"] is None and check["effect_rub_month"] is None
    with Session(owner_engine) as s:
        assert s.execute(select(Task).where(Task.experiment_id == UUID(check["id"]))).first() is None
    [entry] = _audit(owner_engine, "experiment.propose", UUID(check["id"]))
    with Session(owner_engine) as s:
        assert entry.user_id == s.execute(select(User.id).where(User.email == "analyst@a.ru")).scalar_one()


@pytest.mark.parametrize("weeks", [0, 3, 8])
def test_a_proposal_takes_only_the_offered_durations(client: TestClient, place: Place, weeks: int) -> None:
    """TC-EXP-04. Only 2, 4 or 6 weeks."""
    analyst = login(client, "analyst@a.ru")
    r = client.post("/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese, weeks=weeks))
    assert r.status_code == 422
    assert client.get("/api/checks", headers=analyst, params={"status": "proposed"}).json() == []


def test_a_proposal_compares_only_with_other_restaurants_of_the_network(
    client: TestClient, place: Place, network: Network
) -> None:
    """TC-EXP-05. The test restaurant itself and another network's restaurant are not a control — 422."""
    analyst = login(client, "analyst@a.ru")
    for control in (place.r["A1"], network.b.restaurants["B1"]):
        body = _propose(client, analyst, place.cheese, control_ids=[str(control)])
        assert client.post("/api/checks", headers=analyst, json=body).status_code == 422
    # A non-suggested restaurant of the network may be chosen.
    body = _propose(client, analyst, place.cheese, control_ids=[str(place.r["A5"])])
    assert client.post("/api/checks", headers=analyst, json=body).status_code == 201


def test_a_running_check_blocks_a_second_one_of_the_same_finding(client: TestClient, place: Place) -> None:
    """TC-EXP-06. While a check is running a second one of the same finding is refused (422)."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    body = _propose(client, analyst, place.cheese)
    first = client.post("/api/checks", headers=analyst, json=body).json()
    assert client.post(f"/api/checks/{first['id']}/launch", headers=hq).status_code == 200
    again = client.post("/api/checks", headers=analyst, json=body)
    assert again.status_code == 422 and "уже есть проверка" in again.json()["detail"]


def test_after_a_rejection_the_same_finding_can_be_proposed_again(client: TestClient, place: Place) -> None:
    """TC-EXP-06. Rejected → not open: the finding may get a new proposal."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    body = _propose(client, analyst, place.cheese)
    first = client.post("/api/checks", headers=analyst, json=body).json()
    assert client.post(f"/api/checks/{first['id']}/reject", headers=hq).status_code == 200
    assert client.post("/api/checks", headers=analyst, json=body).status_code == 201


# ------------------------------------------------------------------ launch and reject (docs/05, steps 4–5)


def test_launch_sets_one_task_per_test_restaurant_and_none_for_the_control(
    client: TestClient, place: Place, owner_engine: Engine
) -> None:
    """TC-EXP-07. The task: title = the change, due = end of the check, set by HQ, linked to the check and the
    finding; control restaurants get nothing; the finding goes to «in_experiment»; who and when is kept."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    check = client.post("/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese)).json()
    r = client.post(f"/api/checks/{check['id']}/launch", headers=hq)
    assert r.status_code == 200, r.text
    [task] = r.json()
    assert (task["title"], task["due_on"], task["assigned_by"], task["status"]) == (
        "Взвешивать сыр на раздаче",
        "2026-11-23",
        "hq",
        "assigned",
    )
    detail = client.get(f"/api/checks/{check['id']}", headers=hq).json()
    assert detail["status"] == "running" and detail["starts_on"] == "2026-10-26"  # the start stays
    assert [t["id"] for t in detail["tasks"]] == [task["id"]]
    assert client.get(f"/api/findings/{place.cheese}", headers=hq).json()["status"] == "in_experiment"
    # The test restaurant's director sees the task; the control's directors (A2, A3, A4) do not.
    assert "Взвешивать сыр на раздаче" in {
        t["title"] for t in client.get("/api/tasks", headers=login(client, "director1@a.ru")).json()
    }
    for email in ("director2@a.ru", "director3@a.ru", "director4@a.ru"):
        theirs = client.get("/api/tasks", headers=login(client, email)).json()
        assert check["id"] not in {t["experiment_id"] for t in theirs}, email
    with Session(owner_engine) as s:
        exp = s.get(Experiment, UUID(check["id"]))
        admin = s.execute(select(User.id).where(User.email == "admin@a.ru")).scalar_one()
        assert exp is not None and exp.decided_by == admin and exp.decided_at is not None
        row = s.get(Task, UUID(task["id"]))
        assert row is not None and (row.finding_id, row.created_on) == (place.cheese, TODAY)
    assert len(_audit(owner_engine, "experiment.launch", UUID(check["id"]))) == 1


def test_a_late_launch_starts_today_and_one_that_would_end_before_it_starts_is_refused(
    client: TestClient, place: Place, owner_engine: Engine, network: Network
) -> None:
    """TC-EXP-08. Proposed to start 01.10 and end 30.10, launched on 23.10 → starts 23.10, ends 30.10.
    A check ending today (23.10) or earlier cannot be launched (422) and stays proposed, with no task."""
    a = network.a
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():

        def proposed(ends: date) -> Experiment:
            e = Experiment(
                tenant_id=a.id,
                title="Обучить по ТТК",
                hypothesis="…",
                metric="перерасход",
                test_restaurant_ids=[a.restaurants["A1"]],
                starts_on=date(2026, 10, 1),
                ends_on=ends,
                expected_rub_month=D("1000.00"),
            )
            s.add(e)
            s.flush()
            return e

        late, over = proposed(date(2026, 10, 30)), proposed(TODAY)
    hq = login(client, "admin@a.ru")
    refused = client.post(f"/api/checks/{over.id}/launch", headers=hq)
    assert refused.status_code == 422
    assert client.get(f"/api/checks/{over.id}", headers=hq).json()["tasks"] == []
    assert client.get(f"/api/checks/{over.id}", headers=hq).json()["status"] == "proposed"
    assert client.post(f"/api/checks/{late.id}/launch", headers=hq).status_code == 200
    detail = client.get(f"/api/checks/{late.id}", headers=hq).json()
    # Launched late: the whole period moves, its length (29 days) stays as approved (code review 7, p. 6)
    assert (detail["starts_on"], detail["ends_on"]) == ("2026-10-23", "2026-11-21")


def test_a_check_of_a_finding_waiting_for_the_review_is_not_launched(
    client: TestClient, place: Place, owner_engine: Engine, network: Network
) -> None:
    """TC-EXP-09. Even if such a check exists (made before the review was switched on), its launch is 422."""
    a = network.a
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        e = Experiment(
            tenant_id=a.id,
            finding_id=place.pending,
            title="Обучить по ТТК",
            hypothesis="…",
            metric="перерасход",
            test_restaurant_ids=[a.restaurants["A2"]],
            starts_on=date(2026, 10, 26),
            ends_on=date(2026, 11, 23),
            expected_rub_month=D("1000.00"),
        )
        s.add(e)
    hq = login(client, "admin@a.ru")
    r = client.post(f"/api/checks/{e.id}/launch", headers=hq)
    assert r.status_code == 422 and "проверку" in r.json()["detail"]
    assert client.get(f"/api/checks/{e.id}", headers=hq).json()["status"] == "proposed"


def test_only_a_proposed_check_is_launched_or_rejected(
    client: TestClient, place: Place, owner_engine: Engine
) -> None:
    """TC-EXP-10. Reject records who and when (audit); a rejected or completed check is neither launched nor
    rejected again (422) and sets no task."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    check = client.post("/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese)).json()
    rejected = client.post(f"/api/checks/{check['id']}/reject", headers=hq)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert len(_audit(owner_engine, "experiment.reject", UUID(check["id"]))) == 1
    for cid in (check["id"], str(place.worked)):
        for action in ("launch", "reject"):
            assert client.post(f"/api/checks/{cid}/{action}", headers=hq).status_code == 422, (cid, action)
    assert client.get(f"/api/checks/{check['id']}", headers=hq).json()["tasks"] == []
    assert client.get(f"/api/findings/{place.cheese}", headers=hq).json()["status"] == "new"


def test_no_route_changes_a_checks_design_after_it_is_proposed(client: TestClient) -> None:
    """TC-EXP-11 (docs/05, «Честность замера»: the design is fixed before the start). Nothing edits or deletes
    a check: no PUT, PATCH or DELETE on any /checks route, and the proposal is the only POST that takes a body
    with the metric, groups and dates."""
    paths = client.get("/openapi.json").json()["paths"]
    checks = {path: item for path, item in paths.items() if path.startswith("/api/checks")}
    assert checks, "the checks routes are in the schema"
    edits = [(m, p) for p, item in checks.items() for m in item if m in ("put", "patch", "delete")]
    assert edits == []
    with_body = sorted(p for p, item in checks.items() if "requestBody" in item.get("post", {}))
    # «Повторить дольше» (stage 7) takes only the weeks and makes a new check: the old one stays as it was
    assert with_body == ["/api/checks", "/api/checks/{check_id}/repeat"]


# ------------------------------------------------------------------ roles


def test_who_does_what_with_checks(client: TestClient, place: Place) -> None:
    """TC-EXP-12. The analyst drafts and proposes but does not launch, reject or roll out (403); a director
    has no checks at all — every /checks route is 403, even for their own restaurant's finding."""
    analyst, director = login(client, "analyst@a.ru"), login(client, "director1@a.ru")
    check = client.post("/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese)).json()
    for action in ("launch", "reject"):
        assert client.post(f"/api/checks/{check['id']}/{action}", headers=analyst).status_code == 403
    assert client.post(f"/api/checks/{place.worked}/rollout", headers=analyst).status_code == 403
    finding = {"finding_id": str(place.cheese)}
    assert client.get("/api/checks", headers=director).status_code == 403
    assert client.get("/api/checks/draft", headers=director, params=finding).status_code == 403
    body = {**finding, "action": "Взвешивать сыр на раздаче", "control_ids": [], "weeks": 4}
    assert client.post("/api/checks", headers=director, json=body).status_code == 403
    assert client.get(f"/api/checks/{check['id']}", headers=director).status_code == 403
    for action in ("launch", "reject", "rollout"):
        assert client.post(f"/api/checks/{check['id']}/{action}", headers=director).status_code == 403
    assert client.get(f"/api/checks/{check['id']}", headers=analyst).json()["status"] == "proposed"


def test_another_networks_checks_are_not_found_and_not_listed(client: TestClient, place: Place) -> None:
    """TC-EXP-13 (CLAUDE.md, principle 2). Network A's admin: B's check by id — 404 for open, launch, reject,
    roll-out; B's checks are not in the list; B's admin sees only B's check."""
    hq_a, hq_b = login(client, "admin@a.ru"), login(client, "admin@b.ru")
    assert client.get(f"/api/checks/{place.foreign_check}", headers=hq_a).status_code == 404
    for action in ("launch", "reject", "rollout"):
        assert client.post(f"/api/checks/{place.foreign_check}/{action}", headers=hq_a).status_code == 404
    assert str(place.foreign_check) not in {c["id"] for c in client.get("/api/checks", headers=hq_a).json()}
    assert [c["title"] for c in client.get("/api/checks", headers=hq_b).json()] == ["Чужая проверка"]
    body = {"finding_id": str(place.foreign_finding), "action": "Взвешивать сыр на раздаче", "weeks": 4}
    assert client.post("/api/checks", headers=hq_a, json=body).status_code == 404


# ------------------------------------------------------------------ roll-out (docs/05, step 7)


def test_rollout_sends_the_change_to_every_other_restaurant_of_the_network_once(
    client: TestClient, place: Place, owner_engine: Engine
) -> None:
    """TC-EXP-14. A3's confirmed check → one task each for A1, A2, A4, A5 (by code; not A3 that did it, not
    network B's B1), due today + 14 days = 06.11; the date of the roll-out is kept; a second time — 422."""
    hq = login(client, "admin@a.ru")
    r = client.post(f"/api/checks/{place.worked}/rollout", headers=hq)
    assert r.status_code == 200, r.text
    tasks = r.json()
    assert [t["restaurant_code"] for t in tasks] == ["A1", "A2", "A4", "A5"]
    assert {(t["title"], t["due_on"], t["assigned_by"]) for t in tasks} == {
        ("Малые партии зелени", "2026-11-06", "hq")
    }
    detail = client.get(f"/api/checks/{place.worked}", headers=hq).json()
    assert detail["rollout_on"] == "2026-10-23" and len(detail["tasks"]) == 5  # the check's own + 4
    assert client.post(f"/api/checks/{place.worked}/rollout", headers=hq).status_code == 422
    [entry] = _audit(owner_engine, "experiment.rollout", place.worked)
    assert entry.payload == {"restaurants": 4}


def test_only_a_confirmed_check_is_rolled_out(client: TestClient, place: Place) -> None:
    """TC-EXP-15. Inconclusive, proposed and running checks are not rolled out (422) and set no task."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    proposed = client.post(
        "/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese)
    ).json()
    assert client.post(f"/api/checks/{proposed['id']}/rollout", headers=hq).status_code == 422
    assert client.post(f"/api/checks/{proposed['id']}/launch", headers=hq).status_code == 200
    for cid in (proposed["id"], str(place.unclear)):
        assert client.post(f"/api/checks/{cid}/rollout", headers=hq).status_code == 422, cid
    assert len(client.get(f"/api/checks/{proposed['id']}", headers=hq).json()["tasks"]) == 1
    assert client.get(f"/api/checks/{place.unclear}", headers=hq).json()["tasks"] == []


# ------------------------------------------------------------------ the result: by the measurement only


def _running(owner_engine: Engine, network: Network, *, done: bool) -> tuple[UUID, UUID, UUID]:
    """A running check of A1 and A2: A1's task done, A2's in progress."""
    a = network.a
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        e = Experiment(
            tenant_id=a.id,
            title="Обучить по ТТК",
            hypothesis="…",
            metric="перерасход",
            test_restaurant_ids=[a.restaurants["A1"], a.restaurants["A2"]],
            starts_on=date(2026, 9, 21),
            ends_on=date(2026, 10, 19),
            expected_rub_month=D("10000.00"),
            status="running",
        )
        s.add(e)
        s.flush()
        common = {
            "tenant_id": a.id,
            "experiment_id": e.id,
            "title": e.title,
            "assigned_by": "hq",
            "created_on": date(2026, 9, 21),
            "due_on": date(2026, 10, 19),
        }
        t1 = Task(
            **common,
            restaurant_id=a.restaurants["A1"],
            status="done",
            done_on=date(2026, 10, 19),
            report="ok",
        )
        t2 = Task(**common, restaurant_id=a.restaurants["A2"], status="in_progress")
        if not done:
            t1.status, t1.done_on, t1.report = "in_progress", None, None
        s.add_all([t1, t2])
    return e.id, t1.id, t2.id


@pytest.mark.parametrize(
    ("verdict", "task_verdict"),
    [
        (Verdict.CONFIRMED, "confirmed"),
        (Verdict.INCONCLUSIVE, "not_confirmed"),
        (Verdict.REJECTED, "not_confirmed"),
    ],
)
def test_the_result_completes_the_check_and_reaches_only_its_done_tasks(
    owner_engine: Engine, network: Network, place: Place, verdict: Verdict, task_verdict: str
) -> None:
    """TC-EXP-16. The check gets status «completed», the verdict, the effect with its interval, the text and
    the date; its done task gets the verdict (confirmed → confirmed, otherwise not confirmed) and the text, no
    money — the effect stays on the check, so it is never counted twice; a task not done is untouched."""
    eid, done_id, open_id = _running(owner_engine, network, done=True)
    with Session(owner_engine) as s, s.begin():
        exp = s.get(Experiment, eid)
        assert exp is not None
        # The effect on the edge of the interval is inside it.
        record_result(
            s,
            exp,
            verdict=verdict,
            effect_rub_month=D("1200.00"),
            ci_low=D("1200.00"),
            ci_high=D("2500.00"),
            text="−1,2 п.п.",
            completed_on=date(2026, 10, 22),
        )
    with Session(owner_engine) as s:
        exp = s.get(Experiment, eid)
        assert exp is not None
        assert (
            exp.status,
            exp.verdict,
            exp.effect_rub_month,
            exp.ci_low_rub_month,
            exp.ci_high_rub_month,
        ) == (
            "completed",
            verdict,
            D("1200.00"),
            D("1200.00"),
            D("2500.00"),
        )
        assert (exp.result_text, exp.completed_on) == ("−1,2 п.п.", date(2026, 10, 22))
        done, still = s.get(Task, done_id), s.get(Task, open_id)
        assert done is not None and still is not None
        assert (
            done.outcome_verdict,
            done.outcome_text,
            done.outcome_measured_on,
            done.outcome_effect_rub_month,
        ) == (
            task_verdict,
            "−1,2 п.п.",
            date(2026, 10, 22),
            None,
        )
        assert (still.outcome_verdict, still.outcome_text) == (None, None)


def test_only_a_running_check_gets_a_result_and_only_inside_its_interval(
    owner_engine: Engine, network: Network, place: Place
) -> None:
    """TC-EXP-17. A completed (or proposed) check → InvalidError; an effect above the interval → InvalidError;
    nothing is written."""
    eid, _, _ = _running(owner_engine, network, done=False)
    kw = {"verdict": Verdict.CONFIRMED, "text": "x", "completed_on": TODAY}
    with Session(owner_engine) as s, s.begin():
        exp = s.get(Experiment, eid)
        assert exp is not None
        with pytest.raises(InvalidError):
            record_result(s, exp, effect_rub_month=D("2501"), ci_low=D("1200"), ci_high=D("2500"), **kw)  # type: ignore[arg-type]
        assert exp.status == "running" and exp.verdict is None
        for done in (place.worked, place.unclear):
            finished = s.get(Experiment, done)
            assert finished is not None
            with pytest.raises(InvalidError):
                record_result(s, finished, effect_rub_month=D(1), ci_low=D(0), ci_high=D(2), **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ «Сэкономлено с помощью AI» (docs/05)


def test_saved_counts_confirmed_checks_once_plus_task_results_outside_checks_within_the_network(
    client: TestClient, owner_engine: Engine, network: Network, place: Place
) -> None:
    """TC-EXP-18. Network A: the confirmed check 5 200 (its done task, also «confirmed», adds nothing) +
    a newly measured confirmed check 1 200 + a task outside checks confirmed at 900 = 7 300 ₽ a month.
    The inconclusive check (3 000, effect above zero) is not counted; network B's 50 000 is not in A,
    and B sees exactly its 50 000. Overview of the network and the head report say the same."""
    eid, _, _ = _running(owner_engine, network, done=True)
    with Session(owner_engine) as s, s.begin():
        exp = s.get(Experiment, eid)
        assert exp is not None
        record_result(
            s,
            exp,
            verdict=Verdict.CONFIRMED,
            effect_rub_month=D("1200.00"),
            ci_low=D("300.00"),
            ci_high=D("2100.00"),
            text="…",
            completed_on=date(2026, 10, 20),
        )
        s.add(
            Task(
                tenant_id=network.a.id,
                restaurant_id=network.a.restaurants["A4"],
                title="Своя мера",
                assigned_by="hq",
                created_on=date(2026, 9, 1),
                due_on=date(2026, 9, 15),
                status="done",
                done_on=date(2026, 9, 15),
                report="ok",
                outcome_verdict="confirmed",
                outcome_effect_rub_month=D("900.00"),
                outcome_measured_on=date(2026, 10, 1),
            )
        )
    hq_a, hq_b = login(client, "admin@a.ru"), login(client, "admin@b.ru")
    net = client.get("/api/overview/network", headers=hq_a, params={"preset": "4w"})
    assert net.status_code == 200, net.text
    assert D(net.json()["confirmed"]) == D("7300")  # 5 200 + 1 200 + 900
    report = client.get("/api/reports/head", headers=hq_a, params={"preset": "13w"}).json()
    assert D(report["confirmed_rub_month"]) == D("7300")
    assert D(report["confirmed_rub_year"]) == D("87600")  # 7 300 × 12
    assert D(
        client.get("/api/overview/network", headers=hq_b, params={"preset": "4w"}).json()["confirmed"]
    ) == D("50000")
    assert D(
        client.get("/api/reports/head", headers=hq_b, params={"preset": "13w"}).json()["confirmed_rub_month"]
    ) == D("50000")


# ------------------------------------------------------------------ after the review of stage 7


def test_a_late_launch_moves_the_period_before_with_it(
    client: TestClient, place: Place, owner_engine: Engine
) -> None:
    """TC-EXP-48 (docs/05 «Периоды»). Proposed on 23.10 for 4 weeks: 26.10–23.11, «до» — 28 days before the
    start, 28.09–25.10. Launched on 30.10: the whole period moves, 30.10–27.11 (28 days, as approved), and
    «до» with it — 02.10–29.10; the task is due on the new end."""
    analyst, hq = login(client, "analyst@a.ru"), login(client, "admin@a.ru")
    made = client.post("/api/checks", headers=analyst, json=_propose(client, analyst, place.cheese)).json()
    assert (made["starts_on"], made["ends_on"]) == ("2026-10-26", "2026-11-23")
    assert made["baseline"] == "28.09–25.10, до проверки"
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 30)
    [task] = client.post(f"/api/checks/{made['id']}/launch", headers=hq).json()
    detail = client.get(f"/api/checks/{made['id']}", headers=hq).json()
    assert (detail["starts_on"], detail["ends_on"], task["due_on"]) == (
        "2026-10-30",
        "2026-11-27",
        "2026-11-27",
    )
    assert detail["baseline"] == "02.10–29.10, до проверки"
    with Session(owner_engine) as s:
        e = s.get(Experiment, UUID(made["id"]))
        assert e is not None and (e.baseline_from, e.baseline_to) == (date(2026, 10, 2), date(2026, 10, 29))


def test_the_designs_and_the_repeat_keep_to_ones_own_network(
    client: TestClient, place: Place, network: Network
) -> None:
    """TC-EXP-50 (CLAUDE.md, principle 2). The proposal's new fields: whatever the design, a restaurant of
    another network is no comparison (422, nothing made); another network's finding — 404 with any design.
    «Повторить дольше»: another network's check — 404 (not 422: it is not seen at all); a director — 403."""
    hq_a, hq_b, director = (
        login(client, "admin@a.ru"),
        login(client, "admin@b.ru"),
        login(client, "director1@a.ru"),
    )
    before = len(client.get("/api/checks", headers=hq_a).json())
    foreign = [str(place.r["A2"]), str(network.b.restaurants["B1"])]
    for key in ("restaurants", "items", "before_after"):
        body = _propose(client, hq_a, place.cheese, design=key, control_ids=foreign)
        assert client.post("/api/checks", headers=hq_a, json=body).status_code == 422, key
        alien = {**body, "finding_id": str(place.foreign_finding), "control_ids": []}
        assert client.post("/api/checks", headers=hq_a, json=alien).status_code == 404, key
        assert (
            client.post("/api/checks", headers=director, json={**body, "control_ids": []}).status_code == 403
        )
    assert len(client.get("/api/checks", headers=hq_a).json()) == before
    assert (
        client.post(f"/api/checks/{place.foreign_check}/repeat", headers=hq_a, json={"weeks": 6}).status_code
        == 404
    )
    assert (
        client.post(f"/api/checks/{place.unclear}/repeat", headers=hq_b, json={"weeks": 6}).status_code == 404
    )
    assert (
        client.post(f"/api/checks/{place.unclear}/repeat", headers=director, json={"weeks": 6}).status_code
        == 403
    )
    assert len(client.get("/api/checks", headers=hq_b).json()) == 1
