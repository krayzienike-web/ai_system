from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.insights.work import TaskFacts, is_late
from app.tasks import service
from app.tasks.models import Task
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["tasks"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class OutcomeOut(BaseModel):
    verdict: str
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
    assigned_by: str
    created_on: date
    due_on: date
    status: str
    late: bool
    done_on: date | None
    report: str | None
    outcome: OutcomeOut | None

    @classmethod
    def of(cls, t: Task, today: date) -> "TaskOut":
        return cls(
            id=t.id,
            restaurant_id=t.restaurant_id,
            finding_id=t.finding_id,
            experiment_id=t.experiment_id,
            title=t.title,
            checklist=t.checklist,
            assigned_by=t.assigned_by,
            created_on=t.created_on,
            due_on=t.due_on,
            status=t.status,
            late=is_late(TaskFacts(t.status, t.due_on), today),
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
        )


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
def list_tasks(ctx: CanRead, session: SessionDep, today: TodayDep) -> list[TaskOut]:
    rows = session.execute(select(Task).order_by(Task.due_on, Task.created_at)).scalars()
    return [TaskOut.of(t, today) for t in rows]


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
    out = [TaskOut.of(t, today) for t in tasks]
    session.commit()
    return out


@router.post("/tasks/{task_id}/start")
def start_task(task_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> TaskOut:
    out = TaskOut.of(service.start_task(session, ctx, task_id), today)
    session.commit()
    return out


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: UUID, body: CompleteIn, ctx: CanRead, session: SessionDep, today: TodayDep
) -> TaskOut:
    out = TaskOut.of(service.complete_task(session, ctx, task_id, report=body.report, today=today), today)
    session.commit()
    return out
