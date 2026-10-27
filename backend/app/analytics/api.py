from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel

from app.analytics import runs
from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["analytics"])


class LatestRunOut(BaseModel):
    """When the findings were last recomputed, and whether a run is waiting or going on now."""

    status: Literal["queued", "running", "done", "failed"]
    trigger: Literal["upload", "manual"]
    requested_at: datetime
    finished_at: datetime | None
    created: int | None
    updated: int | None
    removed: int | None


def _out(run: runs.AnalyticsRun) -> LatestRunOut:
    return LatestRunOut(
        status=run.status,
        trigger=run.trigger,
        requested_at=run.requested_at,
        finished_at=run.finished_at,
        created=run.created,
        updated=run.updated,
        removed=run.removed,
    )


@router.post("/analytics/run", status_code=status.HTTP_202_ACCEPTED)
def run(
    ctx: Annotated[AccessContext, Depends(require(Permission.ANALYTICS_RUN))],
    session: SessionDep,
    today: TodayDep,
    background: BackgroundTasks,
) -> LatestRunOut:
    """Recompute the network's findings: queued like a run after an upload, never inside the request
    (architecture review 27.10.2026, p. 14). The screens follow it through `/analytics/runs/latest`."""
    queued = runs.request(session, ctx, trigger="manual")
    session.commit()
    runs.dispatch(queued, today, background)
    return _out(queued)


@router.get("/analytics/runs/latest")
def latest_run(
    ctx: Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))], session: SessionDep
) -> LatestRunOut | None:
    run = runs.latest(session)
    return None if run is None else _out(run)
