from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.verify import verify
from app.core import words
from app.core.deps import SessionDep, require
from app.core.errors import ForbiddenError, NotFoundError
from app.core.period import TodayDep
from app.insights import review, service
from app.insights.models import Finding, ReviewStatus
from app.insights.review import RejectReason, Verdict
from app.insights.service import FindingWork
from app.insights.work import WorkStage
from app.tasks.api import TaskOut, tasks_out
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant, User
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
    progress_text: str | None = None


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
    restaurant_code: str | None = None
    restaurant_name: str | None = None
    # How it is shown: summary, causes, metric, confidence_note, scale, composition, chart, table (ADR 0007).
    view: dict[str, Any] | None = None


class FindingDetailOut(FindingOut):
    tasks: list[TaskOut]
    check: CheckRef | None  # HQ only: a director follows a check through its tasks
    result_answer: str | None  # «Что сделали и что получилось?» in words; None while nothing is done


def _out(fw: FindingWork, ctx: AccessContext) -> dict[str, object]:
    f = fw.finding
    hq = ctx.can(Permission.FINDINGS_REVIEW)  # why a finding was rejected or reopened is HQ's working note
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
        "review_reason": f.review_reason if hq else None,
        "review_note": f.review_note if hq else None,
        "reviewed_on": f.reviewed_on,
        "title": f.title,
        "headline": f.headline,
        "effect_rub_month": f.effect_rub_month,
        "effect_note": f.effect_note,
        "actions": f.actions,
        "status": f.status,
        "found_on": f.found_on,
        "work": WorkOut(**fw.work.__dict__),
        "view": f.view,
    }


def findings_out(session: Session, ctx: AccessContext, items: list[FindingWork]) -> list[FindingOut]:
    """Findings as the screens get them: with the reviewer's name (HQ) and the restaurant's code and name."""
    reviewers = _reviewer_names(session, [fw.finding for fw in items])
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}
    out = []
    for fw in items:
        place = places.get(fw.finding.restaurant_id) if fw.finding.restaurant_id else None
        out.append(
            FindingOut(
                **_out(fw, ctx),
                reviewed_by_name=reviewers.get(fw.finding.reviewed_by),
                restaurant_code=place.code if place else None,
                restaurant_name=place.name if place else None,
            )
        )
    return out


def result_answer(fw: FindingWork) -> str | None:
    """What came of the work on a finding, measured by the system, not by the people who did it."""
    tasks, e = fw.tasks, fw.experiment
    if not tasks and not e:
        return None
    confirmed = sum(
        (t.outcome_effect_rub_month or Decimal(0) for t in tasks if t.outcome_verdict == "confirmed"),
        Decimal(0),
    )
    if e and e.verdict == "confirmed" and e.effect_rub_month:
        return f"Проверка подтвердила эффект +{words.per_month(e.effect_rub_month)}."
    if confirmed:
        return f"Сработало: +{words.per_month(confirmed)} — посчитано по данным после выполнения."
    done = sum(1 for t in tasks if t.status == "done")
    if done:
        return (
            f"Задачи выполнены ({done} из {len(tasks)}), результат в рублях посчитаем после "
            "ближайшей инвентаризации."
        )
    what = f"задач — {len(tasks)}" if tasks else "идет проверка"
    return f"В работе: {what}. Как только выполнят — здесь появится отчет и результат."


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
    return findings_out(session, ctx, items)


def _reviewer_names(session: Session, findings: list[Finding]) -> dict[UUID | None, str]:
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
            progress_text=e.progress_text,
        )
        if e and ctx.can(Permission.NETWORK_COMPARE)
        else None
    )
    (base,) = findings_out(session, ctx, [fw])
    return FindingDetailOut(
        **base.model_dump(),
        tasks=tasks_out(session, fw.tasks, today),
        check=check,
        result_answer=result_answer(fw),
    )


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
    (out,) = findings_out(session, ctx, [fw])
    session.commit()
    return out
