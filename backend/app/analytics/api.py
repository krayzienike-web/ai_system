from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.analytics import engine
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
    session.commit()
    return RunOut(**result.__dict__)
