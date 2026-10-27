from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import SessionDep, require
from app.core.errors import NotFoundError
from app.core.period import TodayDep
from app.experiments import service
from app.experiments.models import Experiment, ExperimentStatus
from app.insights.models import Finding
from app.tasks.api import TaskOut, tasks_out
from app.tasks.models import Task
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

router = APIRouter(tags=["checks"])

CanCompare = Annotated[AccessContext, Depends(require(Permission.NETWORK_COMPARE))]


class PlaceOut(BaseModel):
    id: UUID
    code: str
    name: str


class CheckOut(BaseModel):
    @computed_field  # type: ignore[prop-decorator]
    @property
    def weeks(self) -> int:
        """How many weeks the check runs."""
        return round((self.ends_on - self.starts_on).days / 7)

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
    status: Literal["proposed", "running", "completed", "rejected"]
    verdict: Literal["confirmed", "inconclusive", "rejected"] | None
    effect_rub_month: Decimal | None
    ci_low_rub_month: Decimal | None
    ci_high_rub_month: Decimal | None
    result_text: str | None
    baseline: str | None
    progress_text: str | None
    rollout_rub_month: Decimal | None
    rollout_on: date | None
    completed_on: date | None
    # What people read (filled by `checks_out`).
    finding_title: str | None = None
    test: list[PlaceOut] = []
    control: list[PlaceOut] = []

    @classmethod
    def of(cls, e: Experiment) -> "CheckOut":
        return cls(**{name: getattr(e, name) for name in cls.model_fields if hasattr(e, name)})


class CheckDetailOut(CheckOut):
    tasks: list[TaskOut]


def checks_out(session: Session, checks: Sequence[Experiment]) -> list[CheckOut]:
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}
    findings = {f.id: f.title for f in session.execute(select(Finding)).scalars()}

    def named(ids: list[UUID]) -> list[PlaceOut]:
        return [PlaceOut(id=i, code=places[i].code, name=places[i].name) for i in ids if i in places]

    out = []
    for e in checks:
        c = CheckOut.of(e)
        c.finding_title = findings.get(e.finding_id) if e.finding_id else None
        c.test, c.control = named(e.test_restaurant_ids), named(e.control_restaurant_ids)
        out.append(c)
    return out


@router.get("/checks")
def list_checks(
    ctx: CanCompare, session: SessionDep, status: Annotated[ExperimentStatus | None, Query()] = None
) -> list[CheckOut]:
    query = select(Experiment).order_by(Experiment.created_at)
    if status is not None:
        query = query.where(Experiment.status == status)
    return checks_out(session, list(session.execute(query).scalars()))


class DurationOut(BaseModel):
    weeks: int
    note: str


class CandidateOut(BaseModel):
    restaurant_id: UUID
    code: str
    name: str
    suggested: bool
    reason: str


class DraftOut(BaseModel):
    finding_id: UUID
    finding_title: str
    actions: list[str]
    test: PlaceOut
    candidates: list[CandidateOut]
    durations: list[DurationOut]
    default_weeks: int
    expected_rub_month: Decimal
    success: str


@router.get("/checks/draft")
def check_draft(finding_id: Annotated[UUID, Query()], ctx: CanCompare, session: SessionDep) -> DraftOut:
    """What the system proposes to check for a finding; HQ adjusts it and sends it for launch."""
    d = service.draft(session, ctx, finding_id)
    return DraftOut(
        finding_id=d.finding.id,
        finding_title=d.finding.title,
        actions=d.actions,
        test=PlaceOut(id=d.test.id, code=d.test.code, name=d.test.name),
        candidates=[CandidateOut(**c.__dict__) for c in d.candidates],
        durations=[DurationOut(weeks=w, note=n) for w, n in d.durations],
        default_weeks=d.default_weeks,
        expected_rub_month=d.expected_rub_month,
        success=d.success,
    )


class ProposeIn(BaseModel):
    finding_id: UUID
    action: str = Field(min_length=1, max_length=300)
    control_ids: list[UUID] = Field(default_factory=list, max_length=50)
    weeks: int


@router.post("/checks", status_code=status.HTTP_201_CREATED)
def propose_check(body: ProposeIn, ctx: CanCompare, session: SessionDep, today: TodayDep) -> CheckOut:
    exp = service.propose(
        session,
        ctx,
        body.finding_id,
        action=body.action,
        control_ids=body.control_ids,
        weeks=body.weeks,
        today=today,
    )
    (out,) = checks_out(session, [exp])
    session.commit()
    return out


@router.get("/checks/{check_id}")
def get_check(check_id: UUID, ctx: CanCompare, session: SessionDep, today: TodayDep) -> CheckDetailOut:
    exp = session.get(Experiment, check_id)
    if exp is None:
        raise NotFoundError("Проверка не найдена")
    (base,) = checks_out(session, [exp])
    tasks = session.execute(
        select(Task).where(Task.experiment_id == exp.id).order_by(Task.created_on)
    ).scalars()
    return CheckDetailOut(**base.model_dump(), tasks=tasks_out(session, list(tasks), today))


@router.post("/checks/{check_id}/rollout")
def rollout_check(check_id: UUID, ctx: CanCompare, session: SessionDep, today: TodayDep) -> list[TaskOut]:
    out = tasks_out(session, service.rollout(session, ctx, check_id, today=today), today)
    session.commit()
    return out


@router.post("/checks/{check_id}/launch")
def launch_check(check_id: UUID, ctx: CanCompare, session: SessionDep, today: TodayDep) -> list[TaskOut]:
    out = tasks_out(session, service.launch(session, ctx, check_id, today=today), today)
    session.commit()
    return out


@router.post("/checks/{check_id}/reject")
def reject_check(check_id: UUID, ctx: CanCompare, session: SessionDep) -> CheckOut:
    (out,) = checks_out(session, [service.reject(session, ctx, check_id)])
    session.commit()
    return out
