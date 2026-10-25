from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.period import Period, PeriodDep, PeriodError, PeriodPreset, resolve_period

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

    @app.get("/p")
    def read(period: PeriodDep) -> dict[str, str]:
        return {"from": period.date_from.isoformat(), "to": period.date_to.isoformat()}

    client = TestClient(app)
    assert client.get("/p", params={"date_from": "2026-10-01", "date_to": "2026-10-18"}).json() == {
        "from": "2026-10-01",
        "to": "2026-10-18",
    }
    assert client.get("/p", params={"preset": "4w"}).status_code == 200
    assert client.get("/p", params={"preset": "month"}).status_code == 422
    assert client.get("/p", params={"date_from": "2026-10-18", "date_to": "2026-10-01"}).status_code == 422
