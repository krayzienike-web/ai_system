"""What is being done about a finding: the stage of the loop "found → doing → checking → result".

HQ follows all work inside findings (docs/ux/03-to-be.md §3), so the list and the card both read it from here.
Pure functions over plain values: no database, fully unit-tested.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.experiments.models import ExperimentStatus, Verdict
from app.insights.models import FindingStatus
from app.tasks.models import OutcomeVerdict, TaskStatus


class WorkStage(StrEnum):
    NEW = "new"
    DOING = "doing"
    CHECKING = "checking"
    DONE = "done"


@dataclass(frozen=True)
class TaskFacts:
    status: str
    due_on: date
    outcome_verdict: str | None = None
    outcome_effect_rub_month: Decimal | None = None


@dataclass(frozen=True)
class ExperimentFacts:
    status: str
    verdict: str | None = None
    effect_rub_month: Decimal | None = None


@dataclass(frozen=True)
class Work:
    stage: WorkStage
    tasks_total: int
    tasks_done: int
    tasks_late: int
    # Confirmed effect, ₽/month: from the check if there is one, otherwise from task outcomes.
    confirmed_rub_month: Decimal
    check_waiting_launch: bool


def is_late(task: TaskFacts, today: date) -> bool:
    return task.status != TaskStatus.DONE and task.due_on < today


def work_of(
    finding_status: str, tasks: list[TaskFacts], experiment: ExperimentFacts | None, today: date
) -> Work:
    done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    late = sum(1 for t in tasks if is_late(t, today))
    live = experiment if experiment and experiment.status != ExperimentStatus.REJECTED else None
    if live and live.verdict == Verdict.CONFIRMED:
        confirmed = live.effect_rub_month or Decimal(0)
    else:
        confirmed = sum(
            (
                t.outcome_effect_rub_month or Decimal(0)
                for t in tasks
                if t.outcome_verdict == OutcomeVerdict.CONFIRMED
            ),
            Decimal(0),
        )

    if (
        finding_status == FindingStatus.RESOLVED
        or confirmed > 0
        or (live and live.status == ExperimentStatus.COMPLETED)
    ):
        stage = WorkStage.DONE
    elif live and live.status == ExperimentStatus.RUNNING:
        stage = WorkStage.CHECKING
    elif tasks or finding_status in (FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT):
        stage = WorkStage.DOING
    else:
        stage = WorkStage.NEW
    return Work(
        stage=stage,
        tasks_total=len(tasks),
        tasks_done=done,
        tasks_late=late,
        confirmed_rub_month=confirmed,
        check_waiting_launch=bool(live and live.status == ExperimentStatus.PROPOSED),
    )
