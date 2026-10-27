from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.experiments.models import Experiment
from app.insights.models import Finding
from app.insights.work import TaskFacts, is_late
from app.tasks import service
from app.tasks.models import Task
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

router = APIRouter(tags=["tasks"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class OutcomeOut(BaseModel):
    verdict: Literal["pending", "confirmed", "not_confirmed"]
    effect_rub_month: Decimal | None
    text: str | None
    measured_on: date | None


class TaskOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    finding_id: UUID | None
    experiment_id: UUID | None
    title: str
    checklist: list[str]
    checklist_done: list[bool]
    assigned_by: Literal["hq", "director"]
    created_on: date
    due_on: date
    status: Literal["assigned", "in_progress", "done"]
    late: bool
    days_left: int  # until the deadline: negative when overdue
    done_on: date | None
    report: str | None
    outcome: OutcomeOut | None
    reminded_on: date | None
    # Where the task came from and where it goes, in words (filled by `tasks_out`).
    source: str | None = None
    finding_title: str | None = None
    finding_effect_rub_month: Decimal | None = None
    restaurant_code: str | None = None
    restaurant_name: str | None = None

    @classmethod
    def of(cls, t: Task, today: date) -> "TaskOut":
        return cls(
            id=t.id,
            restaurant_id=t.restaurant_id,
            finding_id=t.finding_id,
            experiment_id=t.experiment_id,
            title=t.title,
            checklist=t.checklist,
            checklist_done=(list(t.checklist_done or []) + [False] * len(t.checklist))[: len(t.checklist)],
            assigned_by=t.assigned_by,
            created_on=t.created_on,
            due_on=t.due_on,
            status=t.status,
            late=is_late(TaskFacts(t.status, t.due_on), today),
            days_left=(t.due_on - today).days,
            done_on=t.done_on,
            report=t.report,
            outcome=OutcomeOut(
                verdict=t.outcome_verdict,
                effect_rub_month=t.outcome_effect_rub_month,
                text=t.outcome_text,
                measured_on=t.outcome_measured_on,
            )
            if t.outcome_verdict
            else None,
            reminded_on=t.reminded_on,
        )


def tasks_out(session: Session, tasks: Sequence[Task], today: date) -> list[TaskOut]:
    """Tasks with what people read about them: the finding or check they come from, the restaurant."""
    findings = {f.id: f for f in session.execute(select(Finding)).scalars()}
    checks = {e.id: e for e in session.execute(select(Experiment)).scalars()}
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}
    out = []
    for t in tasks:
        task = TaskOut.of(t, today)
        f = findings.get(t.finding_id) if t.finding_id else None
        e = checks.get(t.experiment_id) if t.experiment_id else None
        place = places.get(t.restaurant_id)
        if t.experiment_id is not None:
            # A director does not see checks (HQ's tool); a check's task carries its title.
            task.source = f"Проверка «{e.title if e else t.title}»"
        elif f is None:
            task.source = (
                "Поставлено управляющей компанией" if t.assigned_by == "hq" else "Добавлено директором"
            )
        task.finding_title = f.title if f else None
        task.finding_effect_rub_month = f.effect_rub_month if f else None
        task.restaurant_code = place.code if place else None
        task.restaurant_name = place.name if place else None
        out.append(task)
    return out


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_on: date
    finding_id: UUID | None = None
    # HQ: restaurants to assign to (omit for a finding: its restaurant, or all for a network-wide one).
    # A director omits it: the task is for their own restaurant.
    restaurant_ids: list[UUID] | None = None
    checklist: list[str] = Field(default_factory=list, max_length=20)


class CompleteIn(BaseModel):
    report: str = Field(min_length=1, max_length=2000)


@router.get("/tasks")
def list_tasks(
    ctx: CanRead, session: SessionDep, today: TodayDep, late: Annotated[bool, Query()] = False
) -> list[TaskOut]:
    rows = list(session.execute(select(Task).order_by(Task.due_on, Task.created_at)).scalars())
    if late:
        rows = [t for t in rows if is_late(TaskFacts(t.status, t.due_on), today)]
    return tasks_out(session, rows, today)


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_tasks(body: TaskIn, ctx: CanRead, session: SessionDep, today: TodayDep) -> list[TaskOut]:
    tasks = service.create_tasks(
        session,
        ctx,
        title=body.title,
        due_on=body.due_on,
        today=today,
        finding_id=body.finding_id,
        restaurant_ids=body.restaurant_ids,
        checklist=body.checklist,
    )
    out = tasks_out(session, tasks, today)
    session.commit()
    return out


@router.post("/tasks/{task_id}/start")
def start_task(task_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> TaskOut:
    (out,) = tasks_out(session, [service.start_task(session, ctx, task_id)], today)
    session.commit()
    return out


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: UUID, body: CompleteIn, ctx: CanRead, session: SessionDep, today: TodayDep
) -> TaskOut:
    task = service.complete_task(session, ctx, task_id, report=body.report, today=today)
    (out,) = tasks_out(session, [task], today)
    session.commit()
    return out


class TickIn(BaseModel):
    index: int = Field(ge=0)
    done: bool


@router.post("/tasks/{task_id}/checklist")
def tick(task_id: UUID, body: TickIn, ctx: CanRead, session: SessionDep, today: TodayDep) -> TaskOut:
    (out,) = tasks_out(session, [service.tick(session, ctx, task_id, body.index, body.done)], today)
    session.commit()
    return out


@router.post("/tasks/{task_id}/remind")
def remind(task_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> TaskOut:
    (out,) = tasks_out(session, [service.remind(session, ctx, task_id, today=today)], today)
    session.commit()
    return out
