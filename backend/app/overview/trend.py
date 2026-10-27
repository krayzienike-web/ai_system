"""The weekly trend: «найденный потенциал» at the end of each week and the confirmed effect so far.

A point is the state of the findings when the week is over — what HQ and the director would have seen then —
so the line stays as it was even after the findings change. It is (re)written by the engine run and after
every review verdict for the last full week (idempotent: one point per restaurant and week).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.period import last_full_week_end
from app.experiments.models import Experiment, Verdict
from app.insights.models import Finding, FindingStatus
from app.overview.models import TrendPoint
from app.tasks.models import OutcomeVerdict, Task

ZERO = Decimal(0)
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


def record_week(session: Session, tenant_id: UUID, today: date) -> date:
    """Writes the points of the last full week for the network and each restaurant; returns the week's end."""
    week_end = last_full_week_end(today)
    findings = [
        f
        for f in session.execute(select(Finding).where(Finding.tenant_id == tenant_id)).scalars()
        if f.checked
        and f.found_on <= week_end
        and (
            f.status in OPEN
            or (f.status == FindingStatus.RESOLVED and (f.resolved_on or week_end) > week_end)
        )
    ]
    losses: dict[UUID | None, Decimal] = defaultdict(lambda: ZERO)
    potential: dict[UUID | None, Decimal] = defaultdict(lambda: ZERO)
    count: dict[UUID | None, int] = defaultdict(int)
    for f in findings:
        for where in {None, f.restaurant_id}:
            effect = f.effect_rub_month or ZERO
            if f.kind == "problem":
                losses[where] += effect
            else:
                potential[where] += effect
            count[where] += 1
    returned: dict[UUID | None, Decimal] = defaultdict(lambda: ZERO)
    for e in session.execute(
        select(Experiment).where(Experiment.tenant_id == tenant_id, Experiment.verdict == Verdict.CONFIRMED)
    ).scalars():
        if e.completed_on and e.completed_on <= week_end:
            returned[None] += e.effect_rub_month or ZERO
            for r in e.test_restaurant_ids:
                returned[r] += (e.effect_rub_month or ZERO) / len(e.test_restaurant_ids)
    for t in session.execute(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.outcome_verdict == OutcomeVerdict.CONFIRMED,
            Task.experiment_id.is_(None),
        )
    ).scalars():
        if t.outcome_measured_on and t.outcome_measured_on <= week_end:
            returned[None] += t.outcome_effect_rub_month or ZERO
            returned[t.restaurant_id] += t.outcome_effect_rub_month or ZERO

    session.execute(
        delete(TrendPoint).where(TrendPoint.tenant_id == tenant_id, TrendPoint.week_end == week_end)
    )
    restaurants = {r for r in (set(losses) | set(potential) | set(returned)) if r is not None}
    for where in [None, *sorted(restaurants)]:
        session.add(
            TrendPoint(
                tenant_id=tenant_id,
                restaurant_id=where,
                week_end=week_end,
                losses=losses[where].quantize(Decimal("0.01")),
                potential=potential[where].quantize(Decimal("0.01")),
                open_findings=count[where],
                returned=returned[where].quantize(Decimal("0.01")),
            )
        )
    session.flush()
    return week_end
