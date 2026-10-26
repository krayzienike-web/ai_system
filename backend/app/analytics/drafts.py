"""What a detector proposes; the engine turns drafts into findings (idempotent by `key`)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID


@dataclass
class Draft:
    key: str  # module:restaurant-or-net:object[:extra] — the same problem keeps the same key between runs
    module: str  # M1 … M7
    kind: str  # problem | opportunity
    process: (
        str  # purchasing | receiving | storage | production | writeoffs | inventory | accounting | planning
    )
    restaurant: UUID | None  # None: network-wide (HQ only)
    title: str
    headline: str
    effect_rub_month: Decimal | None
    effect_note: str | None
    confidence: str  # high | medium | low
    period_from: date
    period_to: date
    actions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def per_month(rub: Decimal, start: date, end: date) -> Decimal:
    """Rubles over a period → rubles per 30-day month."""
    days = (end - start).days + 1
    return (rub * 30 / days).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def rub(value: Decimal) -> str:
    """12 345 ₽ — the way numbers are written in titles and headlines."""
    whole = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{whole:,}".replace(",", " ") + " ₽"


def pct(value: Decimal, places: int = 1) -> str:
    q = Decimal(1).scaleb(-places)
    return f"{(value * 100).quantize(q, rounding=ROUND_HALF_UP)}".replace(".", ",") + "%"


def dmy(d: date) -> str:
    return d.strftime("%d.%m")
