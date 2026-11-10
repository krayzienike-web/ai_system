"""Stage 7: the demo network's checks are measured by code after the engine's runs; drafts offer the three
designs with the smallest visible effect; «Повторить дольше» makes a new check (docs/05; TC-EXP-26…38)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.experiments.models import Experiment
from tests.conftest import Network, login
from tests.test_overview import demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)

D = Decimal


def _by_title(client: TestClient, hq: dict[str, str]) -> dict[str, dict]:  # type: ignore[type-arg]
    return {c["title"]: c for c in client.get("/api/checks", headers=hq).json()}


def test_the_history_checks_get_their_results_from_the_data(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-38, 26, 36: R04's tomatoes — confirmed, with the interval and a rollout forecast; R07's bread —
    measured, no effect; R01's mozzarella — running, an interim measurement; none typed by hand."""
    hq = login(client, "admin@a.ru")
    checks = _by_title(client, hq)
    tomato = checks["Малые партии томатов"]
    assert tomato["status"] == "completed" and tomato["verdict"] == "confirmed" and tomato["measured"]
    low, effect, high = (D(tomato[k]) for k in ("ci_low_rub_month", "effect_rub_month", "ci_high_rub_month"))
    assert 0 < low <= effect <= high and D(tomato["rollout_rub_month"]) > 0
    assert tomato["result_text"].startswith("Списано к расходу по техкартам — «Томаты», R04:")
    assert "Разница разниц −" in tomato["result_text"]
    bread = checks["Заказ хлеба по дням недели"]
    assert bread["status"] == "completed" and bread["verdict"] in ("rejected", "inconclusive")
    assert D(bread["ci_low_rub_month"]) <= 0 and bread["rollout_rub_month"] is None
    moz = checks["Контрольное взвешивание сыра"]
    assert moz["status"] == "running" and moz["verdict"] is None and moz["measured_on"] == "2026-10-20"
    assert moz["progress_text"].startswith("За 7 дн. проверки:") and "Судить рано" in moz["progress_text"]
    # the confirmed result is what «Сэкономлено» counts; the one without an effect is not (TC-EXP-25)
    net = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()
    assert D(net["confirmed"]) >= effect


def test_the_draft_offers_the_designs_with_the_smallest_visible_effect(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-29…33, 35: a write-offs finding — all three designs, the in-restaurant control named; the
    before-and-after one marked weak; the hypothesis by the template."""
    hq = login(client, "admin@a.ru")
    greens = next(
        f
        for f in client.get("/api/findings", headers=hq).json()
        if f["title"] == "Списания выше сети: Руккола" and f["restaurant_code"] == "R01"
    )
    d = client.get("/api/checks/draft", headers=hq, params={"finding_id": greens["id"]}).json()
    assert d["measured"] and {o["design"] for o in d["designs"]} == {"restaurants", "items", "before_after"}
    by = {o["design"]: o for o in d["designs"]}
    assert by["restaurants"]["available"] and D(by["restaurants"]["mde_rub_month"]) > 0
    assert by["items"]["available"] and "салат романо" in by["items"]["note"]
    assert by["before_after"]["weak"] and not by["restaurants"]["weak"]
    assert d["recommended"] in ("restaurants", "items")
    # a template: the wizard fills the measure and the length the HQ picks, the proposal stores the same
    assert d["hypothesis"].startswith("Если в ресторане «") and "{action}" in d["hypothesis"]
    assert "за {weeks} — это +" in d["hypothesis"]
    # A finding without a metric of the measurement: no designs, a task only (TC-EXP-34)
    soup = next(f for f in client.get("/api/findings", headers=hq).json() if f["module"] == "M4")
    if soup["restaurant_id"]:
        nd = client.get("/api/checks/draft", headers=hq, params={"finding_id": soup["id"]}).json()
        assert nd["measured"] is False and nd["designs"] == []


def test_a_proposal_fixes_the_chosen_design_and_an_unfit_one_is_refused(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-28, 32: the chosen design is the one stored; unknown — 422; no control restaurants — 422."""
    hq = login(client, "admin@a.ru")
    greens = next(
        f
        for f in client.get("/api/findings", headers=hq).json()
        if f["title"] == "Списания выше сети: Руккола" and f["restaurant_code"] == "R01"
    )
    d = client.get("/api/checks/draft", headers=hq, params={"finding_id": greens["id"]}).json()
    body = {"finding_id": greens["id"], "action": d["actions"][0], "control_ids": [], "weeks": 4}
    assert client.post("/api/checks", headers=hq, json={**body, "design": "magic"}).status_code == 422
    assert client.post("/api/checks", headers=hq, json={**body, "design": "restaurants"}).status_code == 422
    made = client.post("/api/checks", headers=hq, json={**body, "design": "items"})
    assert made.status_code == 201
    check = made.json()
    assert check["design"] == "items" and check["measured"] and check["control"] == []
    assert D(check["mde_rub_month"]) > 0 and check["baseline"].endswith("до проверки")


def test_a_check_without_an_effect_is_repeated_longer_as_a_new_check(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-36, 37: «Повторить дольше» — a new proposed check, longer, the same design; the old one stays;
    not for a confirmed one or a shorter length; the analyst may, a director and another network may not."""
    hq, analyst, director = (
        login(client, "admin@a.ru"),
        login(client, "analyst@a.ru"),
        login(client, "r01@a.ru"),
    )
    foreign = login(client, "admin@b.ru")
    checks = _by_title(client, hq)
    bread, tomato = checks["Заказ хлеба по дням недели"], checks["Малые партии томатов"]
    url = f"/api/checks/{bread['id']}/repeat"
    assert client.post(url, headers=director, json={"weeks": 6}).status_code == 403
    assert client.post(url, headers=foreign, json={"weeks": 6}).status_code == 404  # RLS: not found
    assert client.post(url, headers=hq, json={"weeks": 4}).status_code == 422  # not longer
    assert client.post(f"/api/checks/{tomato['id']}/repeat", headers=hq, json={"weeks": 6}).status_code == 422
    again = client.post(url, headers=analyst, json={"weeks": 6})
    assert again.status_code == 201
    new = again.json()
    assert new["status"] == "proposed" and new["weeks"] == 6 and new["design"] == bread["design"]
    assert new["id"] != bread["id"] and _by_title(client, hq)  # the old one is still there
    old = client.get(f"/api/checks/{bread['id']}", headers=hq).json()
    assert old["status"] == "completed" and old["weeks"] == bread["weeks"]


def test_unmeasured_findings_go_as_tasks_and_a_repeat_is_offered_once(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """Code review of stage 7, p. 3 and frontend p. 5–6: a finding the measurement does not measure
    is no check (422); `repeatable` says when «Повторить дольше» works; then the finding leads to the
    new check."""
    hq = login(client, "admin@a.ru")
    findings = client.get("/api/findings", headers=hq).json()
    m4 = next(f for f in findings if f["module"] == "M4" and f["restaurant_id"])
    d = client.get("/api/checks/draft", headers=hq, params={"finding_id": m4["id"]}).json()
    body = {"finding_id": m4["id"], "action": d["actions"][0], "control_ids": [], "weeks": 4}
    refused = client.post("/api/checks", headers=hq, json={**body, "design": "before_after"})
    assert refused.status_code == 422 and "задачу" in refused.json()["detail"]
    checks = _by_title(client, hq)
    bread, tomato = checks["Заказ хлеба по дням недели"], checks["Малые партии томатов"]
    assert bread["repeatable"] and not tomato["repeatable"]
    new = client.post(f"/api/checks/{bread['id']}/repeat", headers=hq, json={"weeks": 6}).json()
    assert not client.get(f"/api/checks/{bread['id']}", headers=hq).json()["repeatable"]
    card = client.get(f"/api/findings/{bread['finding_id']}", headers=hq).json()
    assert card["check"]["id"] == new["id"] and card["work"]["check_waiting_launch"]


def test_old_checks_get_their_metric_or_close_and_a_late_upload_is_waited_for(
    client: TestClient,
    network: Network,
    owner_engine: Engine,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """Code review of stage 7, p. 3 and 9; TC-EXP-26: a running check from before the measurement — its
    metric from its finding; one that has none closes after its end with the reason; a check whose end is
    after the last uploaded day waits for the data."""
    hq = login(client, "admin@a.ru")
    by_title = {f["title"]: f for f in client.get("/api/findings", headers=hq).json()}
    greens = next(
        f for t, f in by_title.items() if t == "Списания выше сети: Руккола" and f["restaurant_code"] == "R01"
    )
    m4 = next(f for f in by_title.values() if f["module"] == "M4" and f["restaurant_id"])
    with Session(owner_engine) as s, s.begin():

        def running(finding_id: str, title: str, starts: date, ends: date) -> UUID:
            e = Experiment(
                tenant_id=network.a.id,
                finding_id=UUID(finding_id),
                title=title,
                hypothesis="—",
                metric="—",
                test_restaurant_ids=[UUID(greens["restaurant_id"])],
                control_restaurant_ids=[],
                starts_on=starts,
                ends_on=ends,
                expected_rub_month=D(1000),
                status="running",
                design="before_after",
            )
            s.add(e)
            s.flush()
            return e.id

        legacy = running(greens["id"], "Старая проверка рукколы", date(2026, 9, 21), date(2026, 10, 18))
        no_metric = running(
            m4["id"], "Старая проверка по инвентаризации", date(2026, 9, 1), date(2026, 9, 28)
        )
        waiting = running(greens["id"], "Ждет данных", date(2026, 10, 1), date(2026, 10, 19))
    client.post("/api/analytics/run", headers=hq)
    with Session(owner_engine) as s:
        old = s.get(Experiment, legacy)
        assert old is not None and old.metric_kind == "writeoffs" and old.status == "completed"
        closed = s.get(Experiment, no_metric)
        assert closed is not None and closed.status == "completed" and closed.verdict == "inconclusive"
        assert closed.result_text == "Эту меру замер не считает: итог — по задачам ресторанов"
        late = s.get(Experiment, waiting)
        assert late is not None and late.status == "running"
        assert late.progress_text == "Срок прошел; ждем данных по 19.10, чтобы подвести итог."


def _snapshot(client: TestClient, hq: dict[str, str]) -> list[dict]:  # type: ignore[type-arg]
    out = []
    for c in sorted(client.get("/api/checks", headers=hq).json(), key=lambda c: c["id"]):
        detail = client.get(f"/api/checks/{c['id']}", headers=hq).json()
        out.append({**c, "tasks": sorted(t["id"] for t in detail["tasks"])})
    return out


def test_two_engine_runs_on_the_same_rows_change_no_check(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-27 (principle 4). Two more runs of the engine on the same rows: every check — the same status,
    verdict, effect, interval, texts, forecast and dates to the kopeck and the letter, the same tasks (none
    added); a completed check is not measured again (its date of completion stays); «Сэкономлено» the same."""
    hq = login(client, "admin@a.ru")
    was = _snapshot(client, hq)
    saved = client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()["confirmed"]
    assert {c["status"] for c in was} >= {"completed", "running"}
    for _ in range(2):
        assert client.post("/api/analytics/run", headers=hq).status_code == 202
        assert client.get("/api/analytics/runs/latest", headers=hq).json()["status"] == "done"
    assert _snapshot(client, hq) == was
    assert (
        client.get("/api/overview/network", headers=hq, params={"preset": "4w"}).json()["confirmed"] == saved
    )


def test_a_repeat_is_one_at_a_time_up_to_twelve_weeks_and_the_card_leads_to_the_open_check(
    client: TestClient,
    network: Network,
    owner_engine: Engine,
    demo: dict[str, UUID],  # noqa: F811
) -> None:
    """TC-EXP-46, 47 (docs/05 «Статусы»). R07's bread (no effect): 13 weeks — 422; 8 weeks (not one of the
    usual 2/4/6) — a new proposal of 8 weeks; while it is open no second repeat (422) and the card of the
    finding leads to it; rejected — it hides nothing: the card leads back to the bread check, which may be
    repeated again; a rejected proposal itself is not repeated. A completed 12-week check is not repeated."""
    hq = login(client, "admin@a.ru")
    bread = _by_title(client, hq)["Заказ хлеба по дням недели"]
    url = f"/api/checks/{bread['id']}/repeat"
    card = f"/api/findings/{bread['finding_id']}"
    assert client.post(url, headers=hq, json={"weeks": 13}).status_code == 422
    eight = client.post(url, headers=hq, json={"weeks": 8})
    assert eight.status_code == 201, eight.text
    new = eight.json()
    assert new["weeks"] == 8 and new["status"] == "proposed" and new["design"] == bread["design"]
    assert "за 8 недель" in new["hypothesis"]
    assert client.post(url, headers=hq, json={"weeks": 10}).status_code == 422  # one open check at a time
    assert client.get(card, headers=hq).json()["check"]["id"] == new["id"]
    assert client.post(f"/api/checks/{new['id']}/reject", headers=hq).status_code == 200
    assert client.get(card, headers=hq).json()["check"]["id"] == bread["id"]  # a rejection hides nothing
    assert client.get(f"/api/checks/{bread['id']}", headers=hq).json()["repeatable"]
    assert client.post(f"/api/checks/{new['id']}/repeat", headers=hq, json={"weeks": 12}).status_code == 422
    twelve = client.post(url, headers=hq, json={"weeks": 12}).json()
    assert twelve["weeks"] == 12
    with Session(owner_engine) as s, s.begin():
        e = s.get(Experiment, UUID(twelve["id"]))
        assert e is not None
        e.status, e.verdict, e.completed_on = "completed", "inconclusive", date(2026, 10, 20)
        e.effect_rub_month = e.ci_low_rub_month = e.ci_high_rub_month = D(0)
    long = client.get(f"/api/checks/{twelve['id']}", headers=hq).json()
    assert long["weeks"] == 12 and not long["repeatable"]
    assert (
        client.post(f"/api/checks/{twelve['id']}/repeat", headers=hq, json={"weeks": 12}).status_code == 422
    )
