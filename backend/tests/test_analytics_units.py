"""Deterministic building blocks of the engine (principle 1: every number is a tested function)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.analytics import params
from app.analytics.costs import CostBook
from app.analytics.drafts import per_month
from app.analytics.facts import ReceiptRow
from app.analytics.m2 import suggested_price
from app.analytics.stats import med, robust_z

D = Decimal


def test_median_and_robust_z() -> None:
    assert med([D(1), D(3), D(2)]) == D(2)
    assert med([D(1), D(2), D(3), D(4)]) == D("2.5")  # an even count: the middle two averaged
    values = [D(10), D(11), D(12), D(13), D(30)]
    z = robust_z(D(30), values, floor=D("0.01"))
    assert z > 10  # far away from a tight group
    assert robust_z(D(12), values, floor=D("0.01")) == 0
    # Almost equal numbers: the floor keeps a tiny difference from looking huge.
    flat = [D(1), D(1), D(1), D("1.001")]
    assert robust_z(D("1.001"), flat, floor=D("0.01")) == D("0.1")


def test_per_month_scales_to_30_days_and_rounds_half_up() -> None:
    assert per_month(D(1000), date(2026, 9, 1), date(2026, 9, 30)) == D(1000)
    assert per_month(D(1000), date(2026, 9, 1), date(2026, 9, 10)) == D(3000)
    assert per_month(D(1), date(2026, 9, 1), date(2026, 9, 30)) == D(1)
    assert per_month(D("0.5"), date(2026, 9, 1), date(2026, 9, 30)) == D(1)  # half up, not to even


def test_suggested_price_rounds_up_to_the_step() -> None:
    # 198 ₽ cost at a 30 % target → 660 ₽ exactly; 199 ₽ → 663.3 → 670 ₽
    assert suggested_price(D(198), D("0.30")) == D(660)
    assert suggested_price(D(199), D("0.30")) == D(670)
    cfg = replace(params.DEFAULT, M2_PRICE_STEP=D(50))
    assert suggested_price(D(199), D("0.30"), cfg) == D(700)


def test_cost_book_falls_back_to_own_history_then_network() -> None:
    r1, r2, cheese = uuid4(), uuid4(), uuid4()
    rows = [
        ReceiptRow(r1, date(2026, 8, 1), cheese, None, D(10), D(6000)),  # 600 ₽/kg, a month before
        ReceiptRow(r2, date(2026, 9, 10), cheese, None, D(10), D(7000)),
        ReceiptRow(r2, date(2026, 9, 20), cheese, None, D(30), D(24000)),  # weighted: 31 000 / 40 = 775
    ]
    book = CostBook(rows)
    sep_1, sep_30 = date(2026, 9, 1), date(2026, 9, 30)
    own = book.cost(r2, cheese, sep_1, sep_30)
    assert own is not None and own.source == "own" and own.rub_per_unit == D(775)
    history = book.cost(r1, cheese, sep_1, sep_30)
    assert history is not None and history.source == "own_history" and history.rub_per_unit == D(600)
    stranger = uuid4()
    net = book.cost(stranger, cheese, sep_1, sep_30)
    assert net is not None and net.source == "network" and net.rub_per_unit == D(775)
    assert book.cost(stranger, uuid4(), sep_1, sep_30) is None  # never bought: the cost stays unknown


def test_params_convert_between_shown_and_engine_units() -> None:
    share = params.BY_KEY["M1_NET_SHARE"]
    assert share.shown(params.DEFAULT.M1_NET_SHARE) == D(75)  # 0.75 → 75 %
    assert share.stored(D(80)) == D("0.8")
    days = params.BY_KEY["M3_WINDOW_DAYS"]
    assert days.stored(D(28)) == 28 and isinstance(days.stored(D(28)), int)
    assert params.BY_KEY["M1_Z_FLOOR"].shown(D("0.005")) == D("0.5")
    cfg = params.from_overrides({"M1_NET_SHARE": "0.8", "M3_WINDOW_DAYS": "28", "UNKNOWN": "1"})
    got = (cfg.M1_NET_SHARE, cfg.M3_WINDOW_DAYS)
    assert got == (D("0.8"), 28)
    assert cfg.M1_Z == params.DEFAULT.M1_Z  # the rest stay at the defaults
    assert params.from_overrides(None) == params.DEFAULT


@pytest.mark.parametrize("d", params.DEFS, ids=lambda d: d.key)
def test_every_default_lies_within_its_editable_range(d: params.ParamDef) -> None:
    assert d.low <= d.shown(getattr(params.DEFAULT, d.key)) <= d.high
