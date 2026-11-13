"""№ 10. Following a check of a change (docs/07 «ИИ-агенты», ADR 0010; stage 11).

For each running check, once a week (one note per check and week, so «Скрыть» puts away this week's only):
- how far it has gone — the day of the check out of its days, and the interim measurement in the words the
  measurement wrote (`progress_text`): the code's numbers, the agent adds none;
- what may spoil it, found in the data: a restaurant of the check whose exports stopped before the network's
  latest day; a new supplier of the measured product in a restaurant of the check since the start (the
  price or the packing may have changed with it); a public holiday inside the check's days (guests and the
  kitchen work differently).
For a check that ended in the last `DONE_DAYS` days, the result in plain words: the verdict and the effect
the measurement computed. The verdict is the code's (stage 7); the note only tells it.
Nothing is proposed: the HQ reads it and opens the check.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.catalog.models import Supplier
from app.experiments.models import Experiment, ExperimentStatus
from app.operations.models import Receipt, Sale
from app.tenancy.models import Restaurant

DONE_DAYS = 7  # a finished check's result is news for a week
BASELINE_DAYS = 56  # the suppliers «before»: eight weeks before the start
# Public holidays of Russia (days off by the Labour Code, art. 112): month, day.
HOLIDAYS = {(1, d) for d in range(1, 9)} | {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}


def holidays(start: date, end: date) -> list[date]:
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    return [d for d in days if (d.month, d.day) in HOLIDAYS]


def _money(v: Decimal | None) -> str | None:
    return str(v.quantize(Decimal(1))) if v is not None else None


def _stopped(session: Session, ids: list[UUID], names: dict[UUID, str], latest: date) -> list[dict[str, str]]:
    """The restaurants of the check whose sales stop before the network's latest day."""
    last = dict(
        session.execute(
            select(Sale.restaurant_id, func.max(Sale.day))
            .where(Sale.restaurant_id.in_(ids), Sale.day <= latest)
            .group_by(Sale.restaurant_id)
        ).all()
    )
    return [
        {"restaurant": names[r], "last": last[r].isoformat() if r in last else ""}
        for r in ids
        if r in names and (r not in last or last[r] < latest)
    ]


def _new_suppliers(
    session: Session, e: Experiment, ids: list[UUID], names: dict[UUID, str], until: date
) -> list[dict[str, str]]:
    """A supplier of the measured product a restaurant of the check did not buy it from before the start."""
    if e.metric_product_id is None:
        return []
    rows = session.execute(
        select(Receipt.restaurant_id, Receipt.supplier_id, func.min(Receipt.day))
        .where(
            Receipt.product_id == e.metric_product_id,
            Receipt.restaurant_id.in_(ids),
            Receipt.supplier_id.is_not(None),
            Receipt.day >= e.starts_on - timedelta(days=BASELINE_DAYS),
            Receipt.day <= until,
        )
        .group_by(Receipt.restaurant_id, Receipt.supplier_id)
    ).all()
    before = {(r, s) for r, s, first in rows if first < e.starts_on}
    known = {r for r, _ in before}
    suppliers = dict(session.execute(select(Supplier.id, Supplier.name)).all())
    return [
        {"restaurant": names[r], "supplier": suppliers.get(s, "") if s else "", "since": first.isoformat()}
        for r, s, first in sorted(rows, key=lambda x: (names.get(x[0], ""), x[2]))
        if (r, s) not in before and r in known and r in names
    ]


def _running(session: Session, e: Experiment, names: dict[UUID, str], today: date, latest: date) -> NoteDraft:
    ids = [*e.test_restaurant_ids, *e.control_restaurant_ids]
    monday = today - timedelta(days=today.weekday())
    return NoteDraft(
        agent=Agent.CHECK_WATCH,
        audience=Audience.HQ,
        restaurant_id=None,
        key=f"check_watch:{e.id}:{monday.isoformat()}",
        for_date=monday,
        facts={
            "check_id": str(e.id),
            "title": e.title,
            "state": "running",
            "starts_on": e.starts_on.isoformat(),
            "ends_on": e.ends_on.isoformat(),
            "day": min((today - e.starts_on).days + 1, (e.ends_on - e.starts_on).days + 1),
            "days": (e.ends_on - e.starts_on).days + 1,
            "test": [names[r] for r in e.test_restaurant_ids if r in names],
            "control": [names[r] for r in e.control_restaurant_ids if r in names],
            "progress": e.progress_text,
            "measured_on": e.measured_on.isoformat() if e.measured_on else None,
            "data_to": latest.isoformat(),
            "stopped": _stopped(session, ids, names, latest),
            "new_suppliers": _new_suppliers(session, e, ids, names, latest),
            "holidays": [d.isoformat() for d in holidays(e.starts_on, e.ends_on)],
        },
    )


def _done(e: Experiment) -> NoteDraft:
    return NoteDraft(
        agent=Agent.CHECK_WATCH,
        audience=Audience.HQ,
        restaurant_id=None,
        key=f"check_watch:{e.id}:done",
        for_date=e.completed_on or e.ends_on,
        facts={
            "check_id": str(e.id),
            "title": e.title,
            "state": "done",
            "starts_on": e.starts_on.isoformat(),
            "ends_on": e.ends_on.isoformat(),
            "verdict": e.verdict,
            "effect": _money(e.effect_rub_month),
            "ci_low": _money(e.ci_low_rub_month),
            "ci_high": _money(e.ci_high_rub_month),
            "result": e.result_text,
        },
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    names = {r.id: r.name for r in restaurants}
    latest = session.execute(select(func.max(Sale.day)).where(Sale.day <= today)).scalar_one() or today
    out = []
    for e in session.execute(
        select(Experiment)
        .where(Experiment.status.in_((ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED)))
        .order_by(Experiment.starts_on, Experiment.title)
    ).scalars():
        if e.status == ExperimentStatus.RUNNING and e.starts_on <= today:
            out.append(_running(session, e, names, today, latest))
        elif (
            e.status == ExperimentStatus.COMPLETED
            and e.verdict is not None
            and e.completed_on is not None
            and today - timedelta(days=DONE_DAYS) <= e.completed_on <= today
        ):
            out.append(_done(e))
    return out
