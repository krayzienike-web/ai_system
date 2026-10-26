"""Tasks: HQ assigns, a director executes and reports; the outcome is written only by analytics (ADR 0006)."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, InvalidError, NotFoundError
from app.insights.models import Finding, FindingStatus
from app.tasks.models import AssignedBy, OutcomeVerdict, Task, TaskStatus
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

MAX_DUE_DAYS = 90


def _targets(
    session: Session, ctx: AccessContext, finding: Finding | None, restaurant_ids: Sequence[UUID] | None
) -> tuple[list[UUID], AssignedBy]:
    if ctx.role.is_hq:
        if not ctx.can(Permission.TASKS_ASSIGN):
            raise ForbiddenError("Only HQ admins assign tasks")
        if restaurant_ids is None:
            if finding is None:
                raise InvalidError("Choose restaurants for a task without a finding")
            if finding.restaurant_id is not None:
                return [finding.restaurant_id], AssignedBy.HQ
            # A network-wide finding goes to every restaurant.
            return list(
                session.execute(select(Restaurant.id).order_by(Restaurant.code)).scalars()
            ), AssignedBy.HQ
        if not restaurant_ids:
            raise InvalidError("No restaurants chosen")
        for rid in restaurant_ids:
            if session.get(Restaurant, rid) is None:
                raise NotFoundError("Restaurant not found")
        if (
            finding is not None
            and finding.restaurant_id is not None
            and set(restaurant_ids) != {finding.restaurant_id}
        ):
            raise InvalidError("A restaurant's finding can only be assigned to that restaurant")
        return list(dict.fromkeys(restaurant_ids)), AssignedBy.HQ
    if not ctx.can(Permission.TASKS_EXECUTE) or ctx.restaurant_id is None:
        raise ForbiddenError("Not allowed to take tasks")
    if restaurant_ids is not None and list(restaurant_ids) != [ctx.restaurant_id]:
        raise ForbiddenError("A director takes tasks only for their own restaurant")
    return [ctx.restaurant_id], AssignedBy.DIRECTOR


def create_tasks(
    session: Session,
    ctx: AccessContext,
    *,
    title: str,
    due_on: date,
    today: date,
    finding_id: UUID | None = None,
    restaurant_ids: Sequence[UUID] | None = None,
    checklist: Sequence[str] = (),
) -> list[Task]:
    title = title.strip()
    if not title:
        raise InvalidError("Task title is empty")
    if due_on < today:
        raise InvalidError("Due date is in the past")
    if due_on > today + timedelta(days=MAX_DUE_DAYS):
        raise InvalidError(f"Due date is more than {MAX_DUE_DAYS} days ahead")
    finding = None
    if finding_id is not None:
        # Row-level security hides findings outside the caller's scope: same answer as a missing one.
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise NotFoundError("Finding not found")
        if not finding.checked:
            raise InvalidError("Находка еще не прошла проверку: задачи по ней ставят после подтверждения")
    targets, assigned_by = _targets(session, ctx, finding, restaurant_ids)

    tasks = [
        Task(
            tenant_id=ctx.tenant_id,
            restaurant_id=rid,
            finding_id=finding_id,
            title=title,
            checklist=[c.strip() for c in checklist if c.strip()],
            checklist_done=[False for c in checklist if c.strip()],
            assigned_by=assigned_by,
            created_by=ctx.user_id,
            created_on=today,
            due_on=due_on,
            status=TaskStatus.ASSIGNED,
        )
        for rid in targets
    ]
    session.add_all(tasks)
    if finding is not None and finding.status == FindingStatus.NEW:
        finding.status = FindingStatus.IN_WORK
    session.flush()
    for t in tasks:
        audit(
            session,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action="task.create",
            entity="task",
            entity_id=t.id,
            payload={"restaurant_id": str(t.restaurant_id), "assigned_by": assigned_by},
        )
    return tasks


def _own_task(session: Session, ctx: AccessContext, task_id: UUID) -> Task:
    if not ctx.can(Permission.TASKS_EXECUTE):
        raise ForbiddenError("Tasks are executed by the restaurant's director")
    task = session.get(Task, task_id)
    if task is None:
        raise NotFoundError("Task not found")
    return task


def start_task(session: Session, ctx: AccessContext, task_id: UUID) -> Task:
    task = _own_task(session, ctx, task_id)
    if task.status != TaskStatus.ASSIGNED:
        raise InvalidError("Only an assigned task can be started")
    task.status = TaskStatus.IN_PROGRESS
    session.flush()
    return task


def complete_task(session: Session, ctx: AccessContext, task_id: UUID, *, report: str, today: date) -> Task:
    task = _own_task(session, ctx, task_id)
    if task.status == TaskStatus.DONE:
        raise InvalidError("The task is already done")
    report = report.strip()
    if not report:
        raise InvalidError("Describe what was done")
    task.status = TaskStatus.DONE
    task.done_on = today
    task.report = report
    # The money is measured after the next recount; until then the result is pending.
    task.outcome_verdict = OutcomeVerdict.PENDING
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="task.complete",
        entity="task",
        entity_id=task.id,
    )
    return task


def tick(session: Session, ctx: AccessContext, task_id: UUID, index: int, done: bool) -> Task:
    """The director ticks a checklist step of their task (or unticks it)."""
    task = _own_task(session, ctx, task_id)
    if task.status == TaskStatus.DONE:
        raise InvalidError("The task is already done")
    if not 0 <= index < len(task.checklist):
        raise InvalidError("No such checklist step")
    marks = list(task.checklist_done or []) + [False] * (len(task.checklist) - len(task.checklist_done or []))
    marks[index] = done
    task.checklist_done = marks
    session.flush()
    return task


def remind(session: Session, ctx: AccessContext, task_id: UUID, *, today: date) -> Task:
    """HQ reminds the director about an overdue task (once a day is enough)."""
    if not ctx.can(Permission.TASKS_ASSIGN):
        raise ForbiddenError("Directors are reminded by the HQ admin")
    task = session.get(Task, task_id)
    if task is None:
        raise NotFoundError("Task not found")
    if task.status == TaskStatus.DONE or task.due_on >= today:
        raise InvalidError("The task is not overdue")
    task.reminded_on = today
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="task.remind",
        entity="task",
        entity_id=task.id,
    )
    return task


def record_outcome(
    session: Session,
    task: Task,
    *,
    verdict: OutcomeVerdict,
    text: str,
    measured_on: date,
    effect_rub_month: Decimal | None = None,
) -> None:
    """Called by the analytics layer only (no API): a person never types the result of their own task."""
    if task.status != TaskStatus.DONE:
        raise InvalidError("A result is measured only for a done task")
    if verdict == OutcomeVerdict.CONFIRMED and (effect_rub_month is None or effect_rub_month <= 0):
        raise InvalidError("A confirmed result needs a positive effect")
    task.outcome_verdict = verdict
    task.outcome_effect_rub_month = effect_rub_month if verdict != OutcomeVerdict.PENDING else None
    task.outcome_text = text
    task.outcome_measured_on = measured_on
    session.flush()
