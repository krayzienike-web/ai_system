"""The period of the screens that take one (`?preset=` or `?date_from=&date_to=`), as an API dependency.

The rules live in `app/core/period.py`; this adds what needs the data: «с последней инвентаризации» depends on
the stock counts the caller sees. Kept out of `core` so that the core does not depend on the domain
(architecture review 27.10.2026, p. 12).
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import AccessDep, SessionDep
from app.core.period import Period, PeriodError, PeriodPreset, TodayDep, resolve_period
from app.operations.models import InventoryCount


def last_count_day(session: Session, today: date) -> date | None:
    """The day «с последней инвентаризации» starts after: each restaurant's last count at least two days ago,
    the earliest of them (row-level security limits the restaurants to what the caller sees)."""
    per_restaurant = (
        select(func.max(InventoryCount.day).label("day"))
        .where(InventoryCount.day <= today - timedelta(days=2))
        .group_by(InventoryCount.restaurant_id)
        .subquery()
    )
    return session.execute(select(func.min(per_restaurant.c.day))).scalar_one_or_none()


def get_last_count(
    session: SessionDep,
    ctx: AccessDep,  # the access context first: the count days are read under row-level security
    today: TodayDep,
    preset: Annotated[PeriodPreset | None, Query()] = None,
) -> date | None:
    return last_count_day(session, today) if preset is PeriodPreset.SINCE_COUNT else None


def get_period(
    today: TodayDep,
    last_count: Annotated[date | None, Depends(get_last_count)],
    preset: Annotated[PeriodPreset | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Period:
    try:
        return resolve_period(today, preset, date_from, date_to, last_count)
    except PeriodError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


PeriodDep = Annotated[Period, Depends(get_period)]
