from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.period import Period, PeriodDep, PeriodError, PeriodPreset, get_last_count, resolve_period

FRIDAY = date(2026, 10, 23)


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        (PeriodPreset.WEEK, Period(date(2026, 10, 12), date(2026, 10, 18))),
        (PeriodPreset.PREV_WEEK, Period(date(2026, 10, 5), date(2026, 10, 11))),
        (PeriodPreset.FOUR_WEEKS, Period(date(2026, 9, 21), date(2026, 10, 18))),
        (PeriodPreset.THIRTEEN_WEEKS, Period(date(2026, 7, 20), date(2026, 10, 18))),
    ],
)
def test_presets_end_on_last_full_week(preset: PeriodPreset, expected: Period) -> None:
    assert resolve_period(FRIDAY, preset) == expected


def test_month_is_last_full_calendar_month() -> None:
    month = resolve_period(FRIDAY, PeriodPreset.MONTH)
    assert month == Period(date(2026, 9, 1), date(2026, 9, 30))
    assert month.previous() == Period(date(2026, 8, 1), date(2026, 8, 31))
    # On the last day of a month that month is still not over; January looks back to December.
    assert resolve_period(date(2026, 10, 31), PeriodPreset.MONTH) == month
    assert resolve_period(date(2027, 1, 5), PeriodPreset.MONTH) == Period(
        date(2026, 12, 1), date(2026, 12, 31)
    )
    assert Period(date(2026, 3, 1), date(2026, 3, 31)).previous() == Period(
        date(2026, 2, 1), date(2026, 2, 28)
    )


def test_quarter_is_last_full_calendar_quarter_and_compares_with_the_one_before() -> None:
    """Q11 (27.10.2026): «прошлый квартал» — the last full calendar quarter."""
    quarter = resolve_period(FRIDAY, PeriodPreset.QUARTER)
    assert quarter == Period(date(2026, 7, 1), date(2026, 9, 30))
    assert quarter.previous() == Period(date(2026, 4, 1), date(2026, 6, 30))
    # The quarter's last day is not over yet; January looks back to October–December.
    assert resolve_period(date(2026, 9, 30), PeriodPreset.QUARTER) == Period(
        date(2026, 4, 1), date(2026, 6, 30)
    )
    assert resolve_period(date(2027, 1, 5), PeriodPreset.QUARTER) == Period(
        date(2026, 10, 1), date(2026, 12, 31)
    )
    assert Period(date(2026, 1, 1), date(2026, 3, 31)).previous() == Period(
        date(2025, 10, 1), date(2025, 12, 31)
    )


def test_since_the_last_count_runs_from_the_day_after_it_to_yesterday() -> None:
    """Q11 (27.10.2026): «с последней инвентаризации»."""
    assert resolve_period(FRIDAY, PeriodPreset.SINCE_COUNT, last_count=date(2026, 10, 15)) == Period(
        date(2026, 10, 16), date(2026, 10, 22)
    )
    with pytest.raises(PeriodError, match="Инвентаризаций еще не было"):
        resolve_period(FRIDAY, PeriodPreset.SINCE_COUNT)
    with pytest.raises(PeriodError, match="Нет подходящей инвентаризации"):
        resolve_period(FRIDAY, PeriodPreset.SINCE_COUNT, last_count=date(2025, 1, 1))


def test_default_is_last_full_week() -> None:
    assert resolve_period(FRIDAY) == Period(date(2026, 10, 12), date(2026, 10, 18))


def test_on_sunday_the_current_week_is_not_over() -> None:
    assert resolve_period(date(2026, 10, 18)) == Period(date(2026, 10, 5), date(2026, 10, 11))
    assert resolve_period(date(2026, 10, 19)) == Period(date(2026, 10, 12), date(2026, 10, 18))


def test_custom_range_is_inclusive() -> None:
    p = resolve_period(FRIDAY, date_from=date(2026, 10, 1), date_to=date(2026, 10, 18))
    assert p.days == 18
    assert p.previous() == Period(date(2026, 9, 13), date(2026, 9, 30))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"preset": PeriodPreset.WEEK, "date_from": date(2026, 10, 1)},
        {"date_from": date(2026, 10, 1)},
        {"date_from": date(2026, 10, 10), "date_to": date(2026, 10, 1)},
        {"date_from": date(2026, 10, 1), "date_to": date(2026, 10, 24)},
        {"date_from": date(2025, 1, 1), "date_to": date(2026, 10, 1)},
    ],
)
def test_invalid_periods_are_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(PeriodError):
        resolve_period(FRIDAY, **kwargs)


def test_dependency_parses_query_and_rejects_bad_input() -> None:
    app = FastAPI()
    app.dependency_overrides[get_last_count] = lambda: None  # no database here: no counts yet

    @app.get("/p")
    def read(period: PeriodDep) -> dict[str, str]:
        return {"from": period.date_from.isoformat(), "to": period.date_to.isoformat()}

    client = TestClient(app)
    assert client.get("/p", params={"date_from": "2026-10-01", "date_to": "2026-10-18"}).json() == {
        "from": "2026-10-01",
        "to": "2026-10-18",
    }
    assert client.get("/p", params={"preset": "4w"}).status_code == 200
    assert client.get("/p", params={"preset": "month"}).json()["from"].endswith("-01")
    assert client.get("/p", params={"preset": "quarter"}).json()["from"].endswith("-01")
    assert client.get("/p", params={"preset": "since_count"}).status_code == 422  # no counts
    assert client.get("/p", params={"preset": "year"}).status_code == 422
    assert client.get("/p", params={"date_from": "2026-10-18", "date_to": "2026-10-01"}).status_code == 422
