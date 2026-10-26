"""Robust statistics used by detectors: median and MAD-based z-score (docs/02, M1)."""

from decimal import Decimal
from statistics import median

MAD_SCALE = Decimal("1.4826")  # makes MAD comparable to a standard deviation for normal data


def med(values: list[Decimal]) -> Decimal:
    return Decimal(median(values))


def robust_z(value: Decimal, values: list[Decimal], floor: Decimal) -> Decimal:
    """How unusual `value` is among `values`. `floor` keeps a near-identical network from turning
    a tiny difference into a huge z (MAD of almost-equal numbers is almost zero)."""
    m = med(values)
    mad = med([abs(v - m) for v in values]) * MAD_SCALE
    return (value - m) / max(mad, floor)
