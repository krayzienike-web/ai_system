from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics.verify import verify
from app.core.deps import SessionDep, require
from app.core.errors import ForbiddenError, NotFoundError
from app.core.period import TodayDep
from app.insights import review, service
from app.insights.models import Finding, ReviewStatus
from app.insights.review import RejectReason, Verdict
from app.insights.service import FindingWork
from app.insights.work import WorkStage
from app.tasks.api import TaskOut
from app.tenancy.context import AccessContext
from app.tenancy.models import User
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
    module: str | None
    confidence: str | None
    period_from: date | None
    period_to: date | None
    review_status: str | None  # null: made by hand; pending | confirmed | rejected
    review_reason: str | None
    review_note: str | None
    reviewed_on: date | None
    reviewed_by_name: str | None = None  # who confirmed or rejected it (HQ sees names; a director gets none)
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
        "module": f.module,
        "confidence": f.confidence,
        "period_from": f.period_from,
        "period_to": f.period_to,
        "review_status": f.review_status,
        "review_reason": f.review_reason,
        "review_note": f.review_note,
        "reviewed_on": f.reviewed_on,
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
    review: Annotated[ReviewStatus | None, Query(description="Only findings in this review state")] = None,
) -> list[FindingOut]:
    if review is not None and not ctx.can(Permission.FINDINGS_REVIEW):
        raise ForbiddenError("Находки проверяет управляющая компания")
    items = service.list_findings(
        session, today=today, stage=stage, restaurant_id=restaurant_id, late_only=late_only, review=review
    )
    names = _reviewer_names(session, [fw.finding for fw in items])
    return [FindingOut(**_out(fw), reviewed_by_name=names.get(fw.finding.reviewed_by)) for fw in items]


def _reviewer_names(session: SessionDep, findings: list[Finding]) -> dict[UUID | None, str]:
    """Names of the people who reviewed these findings (row-level security hides them from a director)."""
    ids = {f.reviewed_by for f in findings if f.reviewed_by}
    if not ids:
        return {}
    return dict(session.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


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


CanReview = Annotated[AccessContext, Depends(require(Permission.FINDINGS_REVIEW))]


@router.get("/findings/{finding_id}/verification")
def verification(finding_id: UUID, ctx: CanReview, session: SessionDep) -> dict[str, Any]:
    """The finding computed again from the uploaded rows, step by step, with the rule that fired."""
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("Finding not found")
    return verify(session, finding)


class ReviewIn(BaseModel):
    verdict: Verdict
    reason: RejectReason | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.post("/findings/{finding_id}/review")
def review_finding(
    finding_id: UUID, body: ReviewIn, ctx: CanReview, session: SessionDep, today: TodayDep
) -> FindingOut:
    review.review(session, ctx, finding_id, body.verdict, reason=body.reason, note=body.note, today=today)
    fw = service.get_finding(session, finding_id, today=today)
    names = _reviewer_names(session, [fw.finding])
    session.commit()
    return FindingOut(**_out(fw), reviewed_by_name=names.get(fw.finding.reviewed_by))
