"""Recalculation after every upload (docs/12-analytics-engine.md, «Конвейер»).

Publishing, rolling back or re-processing a file asks for a run of the engine: a row in `analytics_runs`.
At most one run waits per network — later uploads join it. The run is executed after the request's
transaction is committed:
- by the arq worker (`app/worker.py`) when `FAI_REDIS_URL` is set — production;
- otherwise right after the response, in the API process (FastAPI background task) — development, tests.
The run works for the whole network, whoever's upload triggered it: the findings it writes are protected by
RLS when read, as always.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.analytics import engine
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.models import Base, IdMixin, TenantMixin
from app.tenancy.context import AccessContext, system_context

log = logging.getLogger(__name__)
STALE = timedelta(minutes=30)  # a run «going on» for longer was interrupted (the process died)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AnalyticsRun(IdMixin, TenantMixin, Base):
    __tablename__ = "analytics_runs"

    trigger: Mapped[str] = mapped_column(String(20))  # upload | manual
    status: Mapped[str] = mapped_column(String(20))
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[int | None] = mapped_column(Integer)
    updated: Mapped[int | None] = mapped_column(Integer)
    removed: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


def request(session: Session, ctx: AccessContext, trigger: str = "upload") -> AnalyticsRun:
    """The network's waiting run, created if there is none (an upload joins the one already waiting).

    Joining updates the waiting row, so it stays locked until this upload commits: the worker, which takes the
    run with FOR UPDATE, waits and then sees this upload's data. A run already taken is not waiting any more —
    the upload queues a new one."""
    now = datetime.now(UTC)
    stmt = insert(AnalyticsRun).values(
        tenant_id=ctx.tenant_id,
        trigger=trigger,
        status=RunStatus.QUEUED,
        requested_by=ctx.user_id,
        requested_at=now,
    )
    run_id = session.execute(
        stmt.on_conflict_do_update(
            index_elements=["tenant_id"],
            index_where=text("status = 'queued'"),
            # The button pressed while an upload's run waits: the run is now the one someone asked for.
            set_={
                "requested_at": stmt.excluded.requested_at,
                "requested_by": stmt.excluded.requested_by,
                "trigger": text(
                    "CASE WHEN excluded.trigger = 'manual' THEN 'manual' ELSE analytics_runs.trigger END"
                ),
            },
        ).returning(AnalyticsRun.id)
    ).scalar_one()
    run = session.get(AnalyticsRun, run_id, populate_existing=True)
    assert run is not None
    return run


def execute(run_id: UUID, tenant_id: UUID, today: date) -> None:
    """Runs a queued run in a session of its own. Safe twice: a run that no longer waits is left alone."""
    with get_sessionmaker()() as session:
        system_context(session, tenant_id)
        # Runs left «going on» by a process that died are failed: the next upload queues a new one.
        session.execute(
            update(AnalyticsRun)
            .where(
                AnalyticsRun.status == RunStatus.RUNNING, AnalyticsRun.started_at < datetime.now(UTC) - STALE
            )
            .values(status=RunStatus.FAILED, finished_at=datetime.now(UTC), error="Пересчет прерван")
        )
        run = session.get(AnalyticsRun, run_id, with_for_update=True)
        if run is None or run.status != RunStatus.QUEUED:
            return
        run.status, run.started_at = RunStatus.RUNNING, datetime.now(UTC)
        session.commit()  # the waiting slot is free: an upload from now on queues the next run
        try:
            ctx = system_context(session, tenant_id)
            result = engine.run(session, ctx, today)
            run.status, run.finished_at = RunStatus.DONE, datetime.now(UTC)
            run.created, run.updated, run.removed = result.created, result.updated, result.removed
            session.commit()
        except Exception as e:
            log.exception("analytics run %s failed", run_id)
            session.rollback()
            system_context(session, tenant_id)
            failed = session.get(AnalyticsRun, run_id)
            if failed is not None:
                failed.status, failed.finished_at = RunStatus.FAILED, datetime.now(UTC)
                failed.error = str(e)[:500]
                session.commit()


def dispatch(run: AnalyticsRun, today: date, background: BackgroundTasks) -> None:
    """After the request's commit: to the worker's queue, or right after the response without one."""
    url = get_settings().redis_url
    if url:
        try:
            asyncio.run(_enqueue(url, run.id, run.tenant_id, today))
            return
        except Exception:
            log.exception("could not queue analytics run %s, running it in the API process", run.id)
    background.add_task(execute, run.id, run.tenant_id, today)


async def _enqueue(url: str, run_id: UUID, tenant_id: UUID, today: date) -> None:
    from arq import create_pool
    from arq.connections import RedisSettings

    pool = await create_pool(RedisSettings.from_dsn(url))
    try:
        await pool.enqueue_job("run_engine", str(run_id), str(tenant_id), today.isoformat())
    finally:
        await pool.aclose()


def latest(session: Session) -> AnalyticsRun | None:
    run = session.execute(
        select(AnalyticsRun).order_by(AnalyticsRun.requested_at.desc()).limit(1)
    ).scalar_one_or_none()
    if (
        run is not None
        and run.status == RunStatus.RUNNING
        and run.started_at is not None
        and run.started_at < datetime.now(UTC) - STALE
    ):
        session.expunge(run)
        run.status, run.error = RunStatus.FAILED, "Пересчет прерван"  # shown so, written by the next run
    return run
