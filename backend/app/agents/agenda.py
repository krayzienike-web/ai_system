"""№ 8. The agenda of the HQ's weekly meeting (docs/07 «ИИ-агенты», ADR 0010; stage 10).

From Monday to Friday the HQ has the week's agenda, about the whole network (no restaurant): the most
expensive open findings, the tasks past their deadline, the checks waiting for a decision and the findings
waiting for one («Ждут решения», ADR 0009). It is computed again every morning, so it says what is true that
day; the next week brings a new one, and over the weekend there is none. It proposes nothing: it is read.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.experiments.models import Experiment, ExperimentStatus
from app.insights.models import Finding, FindingStatus
from app.overview import service as overview
from app.tasks.models import Task, TaskStatus
from app.tenancy.models import Restaurant

TOP_FINDINGS = 5
TOP_LATE = 5
WORK_DAYS = 5  # Monday to Friday
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)


def _place(names: dict[UUID, str], restaurant_id: UUID | None) -> str:
    return names.get(restaurant_id, "") if restaurant_id else "вся сеть"


def draft(session: Session, restaurants: list[Restaurant], today: date) -> NoteDraft | None:
    if today.weekday() >= WORK_DAYS:
        return None
    monday = today - timedelta(days=today.weekday())
    names = {r.id: r.name for r in restaurants}
    findings = session.execute(
        select(Finding)
        .where(Finding.status.in_(OPEN), Finding.effect_rub_month.is_not(None))
        .order_by(Finding.effect_rub_month.desc(), Finding.key)
    ).scalars()
    top = [
        {
            "title": f.title,
            "place": _place(names, f.restaurant_id),
            "effect": str((f.effect_rub_month or Decimal(0)).quantize(Decimal(1))),
            "status": f.status,
        }
        for f in findings
        if f.checked
    ][:TOP_FINDINGS]
    late_rows = list(
        session.execute(
            select(Task)
            .where(Task.status != TaskStatus.DONE, Task.due_on < today)
            .order_by(Task.due_on, Task.title)
        ).scalars()
    )
    late = [
        {"title": t.title, "place": _place(names, t.restaurant_id), "days": (today - t.due_on).days}
        for t in late_rows[:TOP_LATE]
    ]
    proposed = list(
        session.execute(
            select(Experiment.title)
            .where(Experiment.status == ExperimentStatus.PROPOSED)
            .order_by(Experiment.created_at)
        ).scalars()
    )
    awaiting = len(overview.awaiting(session, today))
    if not (top or late or proposed or awaiting):
        return None
    return NoteDraft(
        agent=Agent.HQ_AGENDA,
        audience=Audience.HQ,
        restaurant_id=None,
        key=f"hq_agenda:{monday.isoformat()}",
        for_date=monday,
        facts={
            "week": monday.isoformat(),
            "findings": top,
            "late": late,
            "late_total": len(late_rows),
            "checks": proposed[:TOP_LATE],
            "checks_total": len(proposed),
            "awaiting": awaiting,
        },
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    d = draft(session, restaurants, today)
    return [d] if d is not None else []
