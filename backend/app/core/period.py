"""Reporting period shared by every analytics endpoint and chat tool.

See docs/02-analytics-spec.md, "Период отчета". A period is either a preset resolved against "today"
or an explicit inclusive date range. Weeks run Monday to Sunday, and presets end on the last full week,
so a weekly number never mixes a finished and an unfinished week. «Прошлый месяц» and «прошлый квартал»
are the last full calendar month and quarter. «С последней инвентаризации» runs from the day after the last
stock count to yesterday (Q11); restaurants count on their own days (Q15), so for the network it starts after
the earliest of the restaurants' last counts — every restaurant's own period fits in it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings

MAX_DAYS = 366


class PeriodPreset(StrEnum):
    WEEK = "week"  # last full week
    PREV_WEEK = "prev_week"  # the week before it
    FOUR_WEEKS = "4w"  # last 4 full weeks
    THIRTEEN_WEEKS = "13w"  # last 13 full weeks (a quarter)
    MONTH = "month"  # last full calendar month
    QUARTER = "quarter"  # last full calendar quarter
    SINCE_COUNT = "since_count"  # from the day after the last stock count to yesterday


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
        """The period right before this one: the baseline for "better / worse".
        Whole calendar months (a month, a quarter) compare with as many months before them, anything else
        with the same number of days."""
        if self.date_from.day == 1 and (self.date_to + timedelta(days=1)).day == 1:
            months = (
                (self.date_to.year - self.date_from.year) * 12 + self.date_to.month - self.date_from.month + 1
            )
            end = self.date_from - timedelta(days=1)
            start = end.replace(day=1)
            for _ in range(months - 1):
                start = (start - timedelta(days=1)).replace(day=1)
            return Period(start, end)
        return Period(self.date_from - timedelta(days=self.days), self.date_from - timedelta(days=1))


def last_full_week_end(today: date) -> date:
    """Sunday of the last week that is over: on a Sunday the current week is not over yet."""
    return today - timedelta(days=today.isoweekday())


def resolve_period(
    today: date,
    preset: PeriodPreset | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    last_count: date | None = None,
) -> Period:
    """`last_count` (for «с последней инвентаризации»): the last stock count day the caller sees, at least
    two days ago so that the period has a day of data in it (see `last_count_day`)."""
    if preset is not None and (date_from is not None or date_to is not None):
        raise PeriodError("Pass either a preset or dates, not both")
    if preset is None and date_from is None and date_to is None:
        preset = PeriodPreset.WEEK
    if preset is PeriodPreset.MONTH:
        end = today.replace(day=1) - timedelta(days=1)
        return Period(end.replace(day=1), end)
    if preset is PeriodPreset.QUARTER:
        first_month = (today.month - 1) // 3 * 3 + 1
        end = today.replace(month=first_month, day=1) - timedelta(days=1)
        return Period(end.replace(month=end.month - 2, day=1), end)
    if preset is PeriodPreset.SINCE_COUNT:
        if last_count is None:
            raise PeriodError("Инвентаризаций еще не было: выберите другой период")
        start = last_count + timedelta(days=1)
        end = today - timedelta(days=1)
        if start > end or (end - start).days + 1 > MAX_DAYS:
            raise PeriodError("Нет подходящей инвентаризации: выберите другой период")
        return Period(start, end)
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


def get_today() -> date:
    """Today for the request; tests override this dependency to pin the calendar, the demo stand sets
    FAI_DEMO_TODAY."""
    return get_settings().demo_today or date.today()


TodayDep = Annotated[date, Depends(get_today)]
