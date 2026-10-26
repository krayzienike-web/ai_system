"""Unit cost of a product: weighted average of purchases (docs/02, M2: «средневзвешенная по приходам»).

Prices are as invoiced, VAT included, in rubles per base unit. Fallbacks, in order, when a restaurant bought
nothing in the period: its own purchases over the 90 days before the period ends, then the network's purchases
in the period. No purchases anywhere → no cost, and the money effect stays unknown.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.analytics.facts import ReceiptRow

LOOKBACK_DAYS = 90


@dataclass(frozen=True)
class Cost:
    rub_per_unit: Decimal
    source: str  # "own" | "own_history" | "network"


_EMPTY: tuple[list[ReceiptRow], list[date]] = ([], [])


def _by_day(rows: list[ReceiptRow]) -> tuple[list[ReceiptRow], list[date]]:
    """Purchases sorted by day, with the days alongside for a binary search."""
    ordered = sorted(rows, key=lambda r: r.day)
    return ordered, [r.day for r in ordered]


class CostBook:
    def __init__(self, receipts: list[ReceiptRow]) -> None:
        own: dict[tuple[UUID, UUID], list[ReceiptRow]] = defaultdict(list)
        net: dict[UUID, list[ReceiptRow]] = defaultdict(list)
        for r in receipts:
            own[(r.restaurant, r.product)].append(r)
            net[r.product].append(r)
        self._own = {k: _by_day(v) for k, v in own.items()}
        self._net = {k: _by_day(v) for k, v in net.items()}

    @staticmethod
    def _avg(series: tuple[list[ReceiptRow], list[date]], start: date, end: date) -> Decimal | None:
        rows, days = series
        chosen = rows[bisect_left(days, start) : bisect_right(days, end)]
        qty = sum((r.qty for r in chosen), Decimal(0))
        if qty <= 0:
            return None
        return sum((r.amount for r in chosen), Decimal(0)) / qty

    def cost(self, restaurant: UUID, product: UUID, start: date, end: date) -> Cost | None:
        own = self._own.get((restaurant, product), _EMPTY)
        if (value := self._avg(own, start, end)) is not None:
            return Cost(value, "own")
        if (value := self._avg(own, end - timedelta(days=LOOKBACK_DAYS), end)) is not None:
            return Cost(value, "own_history")
        if (value := self._avg(self._net.get(product, _EMPTY), start, end)) is not None:
            return Cost(value, "network")
        return None
