"""Findings with the work on each of them. Visibility comes from row-level security."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.experiments.models import Experiment, ExperimentStatus
from app.insights.models import Finding
from app.insights.work import ExperimentFacts, TaskFacts, Work, WorkStage, work_of
from app.tasks.models import Task


@dataclass(frozen=True)
class FindingWork:
    finding: Finding
    work: Work
    tasks: list[Task]
    experiment: Experiment | None


def _facts(t: Task) -> TaskFacts:
    return TaskFacts(t.status, t.due_on, t.outcome_verdict, t.outcome_effect_rub_month)


def _experiment_by_finding(session: Session, finding_ids: list[UUID]) -> dict[UUID, Experiment]:
    # A director sees no checks (HQ tool): the map is simply empty for them.
    rows = session.execute(
        select(Experiment).where(Experiment.finding_id.in_(finding_ids)).order_by(Experiment.created_at)
    ).scalars()
    out: dict[UUID, Experiment] = {}
    for e in rows:
        # Prefer a live check over a rejected proposal.
        if e.finding_id and (
            e.finding_id not in out or out[e.finding_id].status == ExperimentStatus.REJECTED
        ):
            out[e.finding_id] = e
    return out


def _with_work(session: Session, findings: list[Finding], today: date) -> list[FindingWork]:
    ids = [f.id for f in findings]
    tasks: dict[UUID, list[Task]] = defaultdict(list)
    for t in session.execute(
        select(Task).where(Task.finding_id.in_(ids)).order_by(Task.created_on)
    ).scalars():
        tasks[t.finding_id].append(t)  # type: ignore[index]
    experiments = _experiment_by_finding(session, ids)
    result = []
    for f in findings:
        exp = experiments.get(f.id)
        facts = ExperimentFacts(exp.status, exp.verdict, exp.effect_rub_month) if exp else None
        result.append(
            FindingWork(
                f, work_of(f.status, [_facts(t) for t in tasks[f.id]], facts, today), tasks[f.id], exp
            )
        )
    return result


def list_findings(
    session: Session,
    *,
    today: date,
    stage: WorkStage | None = None,
    restaurant_id: UUID | None = None,
    late_only: bool = False,
) -> list[FindingWork]:
    query = select(Finding).where(Finding.status != "dismissed")
    if restaurant_id is not None:
        query = query.where(Finding.restaurant_id == restaurant_id)
    findings = list(session.execute(query).scalars())
    items = [
        fw
        for fw in _with_work(session, findings, today)
        if (stage is None or fw.work.stage == stage) and (not late_only or fw.work.tasks_late > 0)
    ]
    # The most expensive first; findings without a ruble estimate last.
    return sorted(
        items, key=lambda fw: (fw.finding.effect_rub_month is None, -(fw.finding.effect_rub_month or 0))
    )


def get_finding(session: Session, finding_id: UUID, *, today: date) -> FindingWork:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("Finding not found")
    return _with_work(session, [finding], today)[0]
