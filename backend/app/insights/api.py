from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.insights import service
from app.insights.service import FindingWork
from app.insights.work import WorkStage
from app.tasks.api import TaskOut
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["findings"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class WorkOut(BaseModel):
    stage: WorkStage
    tasks_total: int
    tasks_done: int
    tasks_late: int
    confirmed_rub_month: Decimal
    check_waiting_launch: bool


class CheckRef(BaseModel):
    id: UUID
    title: str
    status: str
    verdict: str | None
    effect_rub_month: Decimal | None
    expected_rub_month: Decimal
    starts_on: date
    ends_on: date


class FindingOut(BaseModel):
    id: UUID
    restaurant_id: UUID | None
    kind: str
    process: str
    title: str
    headline: str | None
    effect_rub_month: Decimal | None
    effect_note: str | None
    actions: list[str]
    status: str
    found_on: date
    work: WorkOut


class FindingDetailOut(FindingOut):
    tasks: list[TaskOut]
    check: CheckRef | None  # HQ only: a director follows a check through its tasks


def _out(fw: FindingWork) -> dict[str, object]:
    f = fw.finding
    return {
        "id": f.id,
        "restaurant_id": f.restaurant_id,
        "kind": f.kind,
        "process": f.process,
        "title": f.title,
        "headline": f.headline,
        "effect_rub_month": f.effect_rub_month,
        "effect_note": f.effect_note,
        "actions": f.actions,
        "status": f.status,
        "found_on": f.found_on,
        "work": WorkOut(**fw.work.__dict__),
    }


@router.get("/findings")
def list_findings(
    ctx: CanRead,
    session: SessionDep,
    today: TodayDep,
    stage: Annotated[WorkStage | None, Query()] = None,
    restaurant_id: Annotated[UUID | None, Query()] = None,
    late_only: Annotated[bool, Query()] = False,
) -> list[FindingOut]:
    items = service.list_findings(
        session, today=today, stage=stage, restaurant_id=restaurant_id, late_only=late_only
    )
    return [FindingOut(**_out(fw)) for fw in items]


@router.get("/findings/{finding_id}")
def get_finding(finding_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> FindingDetailOut:
    fw = service.get_finding(session, finding_id, today=today)
    e = fw.experiment
    check = (
        CheckRef(
            id=e.id,
            title=e.title,
            status=e.status,
            verdict=e.verdict,
            effect_rub_month=e.effect_rub_month,
            expected_rub_month=e.expected_rub_month,
            starts_on=e.starts_on,
            ends_on=e.ends_on,
        )
        if e
        else None
    )
    return FindingDetailOut(**_out(fw), tasks=[TaskOut.of(t, today) for t in fw.tasks], check=check)
