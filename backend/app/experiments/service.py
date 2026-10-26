"""Checks: HQ launches or rejects a proposal; launching sets tasks for the test restaurants."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, InvalidError, NotFoundError
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.insights.models import Finding, FindingStatus
from app.tasks.models import AssignedBy, OutcomeVerdict, Task, TaskStatus
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission


def _proposal(session: Session, ctx: AccessContext, experiment_id: UUID) -> Experiment:
    if not ctx.can(Permission.EXPERIMENTS_LAUNCH):
        raise ForbiddenError("Only HQ admins launch checks")
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise NotFoundError("Check not found")
    if exp.status != ExperimentStatus.PROPOSED:
        raise InvalidError("The check is not waiting for a decision")
    return exp


def launch(session: Session, ctx: AccessContext, experiment_id: UUID, *, today: date) -> list[Task]:
    exp = _proposal(session, ctx, experiment_id)
    if exp.finding_id is not None:
        finding = session.get(Finding, exp.finding_id)
        if finding is not None and not finding.checked:
            raise InvalidError(
                "Находка еще не прошла проверку: проверку изменений запускают после подтверждения"
            )
    if exp.ends_on <= today:
        raise InvalidError("The check would end before it starts; change its dates")
    exp.status = ExperimentStatus.RUNNING
    exp.starts_on = max(exp.starts_on, today)
    exp.decided_by = ctx.user_id
    exp.decided_at = datetime.now(UTC)
    tasks = [
        Task(
            tenant_id=ctx.tenant_id,
            restaurant_id=rid,
            finding_id=exp.finding_id,
            experiment_id=exp.id,
            title=exp.title,
            assigned_by=AssignedBy.HQ,
            created_by=ctx.user_id,
            created_on=today,
            due_on=exp.ends_on,
            status=TaskStatus.ASSIGNED,
        )
        for rid in exp.test_restaurant_ids
    ]
    session.add_all(tasks)
    if exp.finding_id is not None:
        finding = session.get(Finding, exp.finding_id)
        if finding is not None and finding.status in (FindingStatus.NEW, FindingStatus.IN_WORK):
            finding.status = FindingStatus.IN_EXPERIMENT
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.launch",
        entity="experiment",
        entity_id=exp.id,
    )
    return tasks


def reject(session: Session, ctx: AccessContext, experiment_id: UUID) -> Experiment:
    exp = _proposal(session, ctx, experiment_id)
    exp.status = ExperimentStatus.REJECTED
    exp.decided_by = ctx.user_id
    exp.decided_at = datetime.now(UTC)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.reject",
        entity="experiment",
        entity_id=exp.id,
    )
    return exp


def record_result(
    session: Session,
    exp: Experiment,
    *,
    verdict: Verdict,
    effect_rub_month: Decimal,
    ci_low: Decimal,
    ci_high: Decimal,
    text: str,
    completed_on: date,
) -> None:
    """Called by the measurement (difference in differences) only. The effect stays on the check, so it is
    never counted twice; its done tasks get the verdict as their outcome."""
    if exp.status != ExperimentStatus.RUNNING:
        raise InvalidError("Only a running check gets a result")
    if not ci_low <= effect_rub_month <= ci_high:
        raise InvalidError("The effect must lie inside its interval")
    exp.status = ExperimentStatus.COMPLETED
    exp.verdict = verdict
    exp.effect_rub_month = effect_rub_month
    exp.ci_low_rub_month = ci_low
    exp.ci_high_rub_month = ci_high
    exp.result_text = text
    exp.completed_on = completed_on
    task_verdict = OutcomeVerdict.CONFIRMED if verdict == Verdict.CONFIRMED else OutcomeVerdict.NOT_CONFIRMED
    for task in session.execute(
        select(Task).where(Task.experiment_id == exp.id, Task.status == TaskStatus.DONE)
    ).scalars():
        task.outcome_verdict = task_verdict
        task.outcome_text = text
        task.outcome_measured_on = completed_on
    session.flush()
