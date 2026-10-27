from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import SessionDep, require
from app.core.period import PeriodDep, TodayDep
from app.experiments.api import CheckOut, checks_out
from app.experiments.models import Experiment
from app.overview import service as overview
from app.overview.api import TrendOut
from app.reports.service import head_report
from app.tasks.api import TaskOut, tasks_out
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant, Tenant
from app.tenancy.permissions import Permission

router = APIRouter(tags=["reports"])

CanCompare = Annotated[AccessContext, Depends(require(Permission.NETWORK_COMPARE))]


class FailureOut(BaseModel):
    kind: str
    title: str
    restaurant_ids: list[str]
    reason: str
    where: str = ""  # restaurant names


class HeadReportOut(BaseModel):
    date_from: date
    date_to: date
    found_rub_month: Decimal
    in_work_rub_month: Decimal
    confirmed_rub_month: Decimal
    open_findings_before: int
    open_findings_now: int
    closed_findings: int
    potential_before_rub_month: Decimal
    potential_now_rub_month: Decimal
    tasks_set: int
    tasks_done: int
    done_tasks: list[TaskOut]
    failures: list[FailureOut]
    network_name: str
    confirmed_by_tasks_rub_month: Decimal  # measured results of the done tasks of the period
    trend: TrendOut
    checks: list[CheckOut]


@router.get("/reports/head")
def get_head_report(
    ctx: CanCompare, session: SessionDep, period: PeriodDep, today: TodayDep
) -> HeadReportOut:
    r = head_report(session, period, today=today)
    names = dict(session.execute(select(Restaurant.id, Restaurant.name)).all())
    return HeadReportOut(
        date_from=period.date_from,
        date_to=period.date_to,
        found_rub_month=r.found_rub_month,
        in_work_rub_month=r.in_work_rub_month,
        confirmed_rub_month=r.confirmed_rub_month,
        open_findings_before=r.open_findings_before,
        open_findings_now=r.open_findings_now,
        closed_findings=r.closed_findings,
        potential_before_rub_month=r.potential_before_rub_month,
        potential_now_rub_month=r.potential_now_rub_month,
        tasks_set=r.tasks_set,
        tasks_done=r.tasks_done,
        done_tasks=tasks_out(session, r.done_tasks, today),
        failures=[
            FailureOut(**f.__dict__, where=", ".join(names.get(UUID(i), i) for i in f.restaurant_ids))
            for f in r.failures
        ],
        confirmed_by_tasks_rub_month=sum(
            (
                t.outcome_effect_rub_month or Decimal(0)
                for t in r.done_tasks
                if t.outcome_verdict == "confirmed"
            ),
            Decimal(0),
        ),
        network_name=session.execute(select(Tenant.name)).scalar_one_or_none() or "",
        trend=TrendOut(**overview.trend_of(session, None, period).__dict__),
        checks=checks_out(
            session, list(session.execute(select(Experiment).order_by(Experiment.created_at)).scalars())
        ),
    )
