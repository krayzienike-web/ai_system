from datetime import date
from decimal import Decimal

from app.insights.work import ExperimentFacts, TaskFacts, WorkStage, is_late, work_of

TODAY = date(2026, 10, 23)


def task(status: str = "assigned", due: date = date(2026, 10, 30), **kw: object) -> TaskFacts:
    return TaskFacts(status=status, due_on=due, **kw)  # type: ignore[arg-type]


def test_new_finding_without_work() -> None:
    w = work_of("new", [], None, TODAY)
    assert w.stage is WorkStage.NEW
    assert (w.tasks_total, w.tasks_done, w.tasks_late) == (0, 0, 0)
    assert w.confirmed_rub_month == 0


def test_proposed_check_keeps_finding_new_and_flags_launch() -> None:
    w = work_of("new", [], ExperimentFacts(status="proposed"), TODAY)
    assert w.stage is WorkStage.NEW
    assert w.check_waiting_launch


def test_tasks_mean_doing_and_lateness_is_derived_from_due_date() -> None:
    tasks = [task(), task(due=date(2026, 10, 20)), task("done", due=date(2026, 10, 1))]
    w = work_of("in_work", tasks, None, TODAY)
    assert w.stage is WorkStage.DOING
    assert (w.tasks_total, w.tasks_done, w.tasks_late) == (3, 1, 1)


def test_due_today_is_not_late() -> None:
    assert not is_late(task(due=TODAY), TODAY)
    assert is_late(task(due=date(2026, 10, 22)), TODAY)
    assert not is_late(task("done", due=date(2026, 10, 1)), TODAY)


def test_running_check_means_checking() -> None:
    w = work_of("in_experiment", [task("in_progress")], ExperimentFacts(status="running"), TODAY)
    assert w.stage is WorkStage.CHECKING


def test_confirmed_check_gives_result_from_measurement() -> None:
    exp = ExperimentFacts(status="completed", verdict="confirmed", effect_rub_month=Decimal("5200.00"))
    w = work_of("in_experiment", [task("done", outcome_verdict="pending")], exp, TODAY)
    assert w.stage is WorkStage.DONE
    assert w.confirmed_rub_month == Decimal("5200.00")


def test_check_without_effect_is_a_result_with_zero() -> None:
    exp = ExperimentFacts(status="completed", verdict="rejected", effect_rub_month=Decimal(0))
    w = work_of("in_experiment", [], exp, TODAY)
    assert w.stage is WorkStage.DONE
    assert w.confirmed_rub_month == 0


def test_task_outcomes_add_up_when_there_is_no_check() -> None:
    tasks = [
        task("done", outcome_verdict="confirmed", outcome_effect_rub_month=Decimal("1000.50")),
        task("done", outcome_verdict="confirmed", outcome_effect_rub_month=Decimal("499.50")),
        task("done", outcome_verdict="not_confirmed", outcome_effect_rub_month=Decimal(0)),
    ]
    w = work_of("in_work", tasks, None, TODAY)
    assert w.stage is WorkStage.DONE
    assert w.confirmed_rub_month == Decimal("1500.00")


def test_rejected_proposal_is_ignored() -> None:
    w = work_of("new", [], ExperimentFacts(status="rejected"), TODAY)
    assert w.stage is WorkStage.NEW
    assert not w.check_waiting_launch
