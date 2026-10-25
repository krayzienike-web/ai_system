from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.experiments import service
from app.experiments.models import Experiment, ExperimentStatus
from app.tasks.api import TaskOut
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["checks"])

CanCompare = Annotated[AccessContext, Depends(require(Permission.NETWORK_COMPARE))]


class CheckOut(BaseModel):
    id: UUID
    finding_id: UUID | None
    title: str
    hypothesis: str
    metric: str
    test_restaurant_ids: list[UUID]
    control_restaurant_ids: list[UUID]
    starts_on: date
    ends_on: date
    expected_rub_month: Decimal
    status: str
    verdict: str | None
    effect_rub_month: Decimal | None
    ci_low_rub_month: Decimal | None
    ci_high_rub_month: Decimal | None
    result_text: str | None

    @classmethod
    def of(cls, e: Experiment) -> "CheckOut":
        return cls(**{name: getattr(e, name) for name in cls.model_fields})


@router.get("/checks")
def list_checks(
    ctx: CanCompare, session: SessionDep, status: Annotated[ExperimentStatus | None, Query()] = None
) -> list[CheckOut]:
    query = select(Experiment).order_by(Experiment.created_at)
    if status is not None:
        query = query.where(Experiment.status == status)
    return [CheckOut.of(e) for e in session.execute(query).scalars()]


@router.post("/checks/{check_id}/launch")
def launch_check(check_id: UUID, ctx: CanCompare, session: SessionDep, today: TodayDep) -> list[TaskOut]:
    out = [TaskOut.of(t, today) for t in service.launch(session, ctx, check_id, today=today)]
    session.commit()
    return out


@router.post("/checks/{check_id}/reject")
def reject_check(check_id: UUID, ctx: CanCompare, session: SessionDep) -> CheckOut:
    out = CheckOut.of(service.reject(session, ctx, check_id))
    session.commit()
    return out
