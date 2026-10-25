"""The head report for a period: found / in work / confirmed, dynamics, what worked and what did not.

Every number is computed here from stored rows (CLAUDE.md principle 1); the page only formats it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.period import Period
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.insights.models import Finding, FindingStatus
from app.insights.work import TaskFacts, is_late
from app.tasks.models import OutcomeVerdict, Task, TaskStatus

ZERO = Decimal(0)
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


@dataclass(frozen=True)
class Failure:
    kind: str  # "check_no_effect" | "task_no_effect" | "task_overdue"
    title: str
    restaurant_ids: list[str]
    reason: str


@dataclass
class HeadReport:
    period: Period
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
    done_tasks: list[Task] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)


def _open_on(f: Finding, day: date) -> bool:
    return f.found_on <= day and (f.resolved_on is None or f.resolved_on > day)


def head_report(session: Session, period: Period, *, today: date) -> HeadReport:
    findings = [f for f in session.execute(select(Finding)).scalars() if f.status != FindingStatus.DISMISSED]
    tasks = list(session.execute(select(Task)).scalars())
    experiments = list(session.execute(select(Experiment)).scalars())

    def effect(fs: list[Finding]) -> Decimal:
        return sum((f.effect_rub_month or ZERO for f in fs), ZERO)

    before, end = period.date_from - timedelta(days=1), period.date_to
    open_now = [f for f in findings if f.status in OPEN]
    confirmed = sum(
        (e.effect_rub_month or ZERO for e in experiments if e.verdict == Verdict.CONFIRMED), ZERO
    ) + sum(
        (
            t.outcome_effect_rub_month or ZERO
            for t in tasks
            if t.experiment_id is None and t.outcome_verdict == OutcomeVerdict.CONFIRMED
        ),
        ZERO,
    )

    def in_period(day: date | None) -> bool:
        return day is not None and period.date_from <= day <= period.date_to

    done_tasks = sorted(
        (t for t in tasks if t.status == TaskStatus.DONE and in_period(t.done_on)),
        key=lambda t: t.done_on or today,
    )

    failures = [
        Failure("check_no_effect", e.title, [str(r) for r in e.test_restaurant_ids], e.result_text or "")
        for e in experiments
        if e.status == ExperimentStatus.COMPLETED
        and e.verdict != Verdict.CONFIRMED
        and in_period(e.completed_on)
    ]
    failures += [
        Failure("task_no_effect", t.title, [str(t.restaurant_id)], t.outcome_text or "")
        for t in done_tasks
        if t.experiment_id is None and t.outcome_verdict == OutcomeVerdict.NOT_CONFIRMED
    ]
    failures += [
        Failure("task_overdue", t.title, [str(t.restaurant_id)], f"срок был {t.due_on:%d.%m}")
        for t in tasks
        if is_late(TaskFacts(t.status, t.due_on), min(today, period.date_to + timedelta(days=1)))
    ]

    return HeadReport(
        period=period,
        found_rub_month=effect(open_now),
        in_work_rub_month=effect([f for f in open_now if f.status != FindingStatus.NEW]),
        confirmed_rub_month=confirmed,
        open_findings_before=sum(1 for f in findings if _open_on(f, before)),
        open_findings_now=sum(1 for f in findings if _open_on(f, end)),
        closed_findings=sum(1 for f in findings if in_period(f.resolved_on)),
        potential_before_rub_month=effect([f for f in findings if _open_on(f, before)]),
        potential_now_rub_month=effect([f for f in findings if _open_on(f, end)]),
        tasks_set=sum(1 for t in tasks if in_period(t.created_on)),
        tasks_done=len(done_tasks),
        done_tasks=done_tasks,
        failures=failures,
    )
