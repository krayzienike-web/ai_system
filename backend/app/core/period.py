"""Reporting period shared by every analytics endpoint and chat tool.

See docs/02-analytics-spec.md, "Период отчета". A period is either a preset resolved against "today"
or an explicit inclusive date range. Weeks run Monday to Sunday, and presets end on the last full week,
so a weekly number never mixes a finished and an unfinished week.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

MAX_DAYS = 366


class PeriodPreset(StrEnum):
    WEEK = "week"  # last full week
    PREV_WEEK = "prev_week"  # the week before it
    FOUR_WEEKS = "4w"  # last 4 full weeks
    THIRTEEN_WEEKS = "13w"  # last 13 full weeks (a quarter)


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date  # inclusive

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def previous(self) -> "Period":
        """The period of the same length right before this one: the baseline for "better / worse"."""
        return Period(self.date_from - timedelta(days=self.days), self.date_from - timedelta(days=1))


def last_full_week_end(today: date) -> date:
    """Sunday of the last week that is over: on a Sunday the current week is not over yet."""
    return today - timedelta(days=today.isoweekday())


def resolve_period(
    today: date,
    preset: PeriodPreset | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Period:
    if preset is not None and (date_from is not None or date_to is not None):
        raise PeriodError("Pass either a preset or dates, not both")
    if preset is None and date_from is None and date_to is None:
        preset = PeriodPreset.WEEK
    if preset is not None:
        end = last_full_week_end(today)
        weeks = {
            PeriodPreset.WEEK: 1,
            PeriodPreset.PREV_WEEK: 1,
            PeriodPreset.FOUR_WEEKS: 4,
            PeriodPreset.THIRTEEN_WEEKS: 13,
        }
        if preset is PeriodPreset.PREV_WEEK:
            end -= timedelta(days=7)
        return Period(end - timedelta(days=7 * weeks[preset] - 1), end)
    if date_from is None or date_to is None:
        raise PeriodError("Both date_from and date_to are required")
    if date_from > date_to:
        raise PeriodError("date_from is after date_to")
    if date_to > today:
        raise PeriodError("The period cannot end in the future")
    period = Period(date_from, date_to)
    if period.days > MAX_DAYS:
        raise PeriodError(f"The period is longer than {MAX_DAYS} days")
    return period


def get_period(
    preset: Annotated[PeriodPreset | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Period:
    try:
        return resolve_period(date.today(), preset, date_from, date_to)
    except PeriodError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


PeriodDep = Annotated[Period, Depends(get_period)]
