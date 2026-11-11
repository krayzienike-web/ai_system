"""№ 7. Task control (docs/07 «ИИ-агенты», ADR 0010).

- To the director: a task due within `DUE_DAYS` (today included) and not done — what is left of it.
- To the HQ: a task `STUCK_DAYS` or more past its deadline and not even started — a proposal to move the
  deadline `MOVE_DAYS` ahead. Only an HQ admin moves it. Reassigning is not offered: a task is set to a
  restaurant, not to a person.
A done task, a started one or a moved deadline is a new situation: the old note expires (its key names the
deadline).
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.tasks.models import Task, TaskStatus
from app.tenancy.models import Restaurant

DUE_DAYS = 2
STUCK_DAYS = 3
MOVE_DAYS = 7


def _facts(t: Task, restaurant: Restaurant, today: date) -> dict[str, object]:
    left = [step for step, done in zip(t.checklist, t.checklist_done, strict=False) if not done]
    return {
        "restaurant": restaurant.name,
        "task": t.title,
        "due_on": t.due_on.isoformat(),
        "days_left": (t.due_on - today).days,
        "status": t.status,
        "steps_total": len(t.checklist),
        "steps_left": left,
    }


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    places = {r.id: r for r in restaurants}
    out = []
    for t in session.execute(
        select(Task).where(Task.status != TaskStatus.DONE).order_by(Task.due_on, Task.id)
    ).scalars():
        r = places.get(t.restaurant_id)
        if r is None:
            continue
        days = (t.due_on - today).days
        if 0 <= days <= DUE_DAYS:
            out.append(
                NoteDraft(
                    agent=Agent.TASK_DUE,
                    audience=Audience.DIRECTOR,
                    restaurant_id=r.id,
                    key=f"task_due:{t.id}:{t.due_on.isoformat()}",
                    for_date=t.due_on,
                    task_id=t.id,
                    facts=_facts(t, r, today),
                )
            )
        elif -days >= STUCK_DAYS and t.status == TaskStatus.ASSIGNED:
            move_to = today + timedelta(days=MOVE_DAYS)
            out.append(
                NoteDraft(
                    agent=Agent.TASK_STUCK,
                    audience=Audience.HQ,
                    restaurant_id=r.id,
                    key=f"task_stuck:{t.id}:{t.due_on.isoformat()}",
                    for_date=t.due_on,
                    task_id=t.id,
                    facts={**_facts(t, r, today), "days_late": -days, "move_to": move_to.isoformat()},
                    proposal={"action": "move_due", "due_on": move_to.isoformat()},
                )
            )
    return out
