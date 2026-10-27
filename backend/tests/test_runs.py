"""TC-ENG-21..23: the findings are recomputed after every upload, in the background (docs/12, «Конвейер»)."""

import asyncio
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import worker
from app.analytics import engine, runs
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.period import get_today
from app.main import app
from app.tenancy.context import load_access_context
from tests.conftest import Network, login

TODAY = date(2026, 10, 25)
PRODUCTS = "Код;Наименование;Базовая ед.\nP1;Сыр Моцарелла;кг\n"


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _upload_and_publish(client: TestClient, headers: dict[str, str]) -> None:
    batch = client.post(
        "/api/imports",
        headers=headers,
        data={"template": "products"},
        files={"file": ("p.csv", PRODUCTS.encode(), "text/csv")},
    ).json()
    assert client.post(f"/api/imports/{batch['id']}/publish", headers=headers).status_code == 200


def test_publishing_a_file_recomputes_the_findings(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    hq = login(client, "admin@a.ru")
    assert client.get("/api/analytics/runs/latest", headers=hq).json() is None
    _upload_and_publish(client, hq)
    # Without a queue the run goes right after the response, in the API process.
    latest = client.get("/api/analytics/runs/latest", headers=hq).json()
    assert latest["status"] == "done" and latest["trigger"] == "upload" and latest["finished_at"]
    # Directors see when their findings were updated too, and another network sees nothing of it.
    assert client.get("/api/analytics/runs/latest", headers=login(client, "director1@a.ru")).json() == latest
    assert client.get("/api/analytics/runs/latest", headers=login(client, "admin@b.ru")).json() is None
    with owner_engine.connect() as c:
        query = "SELECT action, user_id FROM audit_log WHERE action = 'analytics.run'"
        actions = c.execute(text(query)).all()
    assert [(a, u) for a, u in actions] == [("analytics.run", None)]  # background work: no person

    # The button queues its run like an upload does (architecture review 27.10.2026, p. 14).
    assert client.post("/api/analytics/run", headers=hq).status_code == 202
    assert client.get("/api/analytics/runs/latest", headers=hq).json()["trigger"] == "manual"


def test_uploads_join_the_waiting_run_and_a_run_goes_once(network: Network) -> None:
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["director1@a.ru"], network.a.id)
        assert ctx is not None
        first, second = runs.request(session, ctx), runs.request(session, ctx)
        assert first.id == second.id and first.status == "queued"
        session.commit()
    runs.execute(first.id, network.a.id, TODAY)
    runs.execute(first.id, network.a.id, TODAY)  # already done: nothing happens
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        done = runs.latest(session)
        assert done is not None and done.status == "done" and done.started_at is not None
        # The slot is free again: the next upload queues a new run.
        assert runs.request(session, ctx).id != first.id


def test_a_failed_run_is_logged(network: Network, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("boom")

    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        run = runs.request(session, ctx)
        session.commit()
    monkeypatch.setattr(engine, "run", broken)
    runs.execute(run.id, network.a.id, TODAY)
    with get_sessionmaker()() as session:
        load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        failed = runs.latest(session)
        assert failed is not None and failed.status == "failed" and failed.error == "boom"


def test_the_queue_is_used_when_configured_and_falls_back_without_it(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[tuple[str, UUID, UUID, date]] = []

    async def enqueue(url: str, run_id: UUID, tenant_id: UUID, today: date) -> None:
        queued.append((url, run_id, tenant_id, today))

    run = runs.AnalyticsRun(id=UUID(int=1), tenant_id=network.a.id, trigger="upload", status="queued")
    monkeypatch.setattr(get_settings(), "redis_url", "redis://queue:6379")
    monkeypatch.setattr(runs, "_enqueue", enqueue)
    background = BackgroundTasks()
    runs.dispatch(run, TODAY, background)
    assert queued == [("redis://queue:6379", run.id, network.a.id, TODAY)] and not background.tasks

    async def unreachable(*_: Any) -> None:
        raise ConnectionError("no redis")

    monkeypatch.setattr(runs, "_enqueue", unreachable)
    runs.dispatch(run, TODAY, background)
    assert len(background.tasks) == 1  # the findings still get recomputed


def test_the_worker_runs_the_queued_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[UUID, UUID, date]] = []
    monkeypatch.setattr(runs, "execute", lambda *a: calls.append(a))
    run_id, tenant_id = UUID(int=1), UUID(int=2)
    asyncio.run(worker.run_engine({}, str(run_id), str(tenant_id), "2026-10-25"))
    assert calls == [(run_id, tenant_id, date(2026, 10, 25))]


def test_an_upload_joining_the_waiting_run_holds_it_until_its_data_is_committed(network: Network) -> None:
    """Code review 27.10.2026: the worker must not take the run while an upload joining it is uncommitted."""
    import threading
    import time

    director = network.a.users["director1@a.ru"]
    with get_sessionmaker()() as first:
        ctx = load_access_context(first, director, network.a.id)
        assert ctx is not None
        run = runs.request(first, ctx)
        first.commit()
    upload = get_sessionmaker()()
    ctx = load_access_context(upload, director, network.a.id)
    assert ctx is not None
    assert runs.request(upload, ctx).id == run.id  # joins the waiting run, not committed yet
    worker_thread = threading.Thread(target=runs.execute, args=(run.id, network.a.id, TODAY))
    worker_thread.start()
    time.sleep(0.5)
    assert worker_thread.is_alive()  # waits for the upload's commit
    upload.commit()
    upload.close()
    worker_thread.join(timeout=30)
    with get_sessionmaker()() as session:
        load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        done = runs.latest(session)
        assert done is not None and done.id == run.id and done.status == "done"


def test_a_run_left_going_on_is_shown_and_then_written_as_interrupted(
    network: Network, owner_engine: Engine
) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO analytics_runs (tenant_id, trigger, status, started_at, requested_at) "
                "VALUES (:t, 'upload', 'running', now() - interval '2 hours', now() - interval '2 hours')"
            ),
            {"t": network.a.id},
        )
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
        stale = runs.latest(session)
        assert stale is not None and stale.status == "failed" and stale.error == "Пересчет прерван"
        fresh = runs.request(session, ctx)
        session.commit()
    runs.execute(fresh.id, network.a.id, TODAY)
    with owner_engine.connect() as conn:
        statuses = (
            conn.execute(text("SELECT status FROM analytics_runs ORDER BY requested_at")).scalars().all()
        )
    assert statuses == ["failed", "done"]
