from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.analytics import engine, runs
from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["analytics"])


class RunOut(BaseModel):
    created: int
    updated: int
    removed: int
    drafts: int


@router.post("/analytics/run")
def run(
    ctx: Annotated[AccessContext, Depends(require(Permission.ANALYTICS_RUN))],
    session: SessionDep,
    today: TodayDep,
) -> RunOut:
    """Recompute findings for the whole network from the data loaded so far."""
    result = engine.run(session, ctx, today)
    runs.record_manual(session, ctx, result)
    session.commit()
    return RunOut(**result.__dict__)


class LatestRunOut(BaseModel):
    """When the findings were last recomputed, and whether a run is waiting or going on now."""

    status: Literal["queued", "running", "done", "failed"]
    trigger: Literal["upload", "manual"]
    requested_at: datetime
    finished_at: datetime | None
    created: int | None
    updated: int | None
    removed: int | None


@router.get("/analytics/runs/latest")
def latest_run(
    ctx: Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))], session: SessionDep
) -> LatestRunOut | None:
    run = runs.latest(session)
    if run is None:
        return None
    return LatestRunOut(
        status=run.status,
        trigger=run.trigger,
        requested_at=run.requested_at,
        finished_at=run.finished_at,
        created=run.created,
        updated=run.updated,
        removed=run.removed,
    )
