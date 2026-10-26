from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class KpiSnapshot(IdMixin, TenantMixin, TimestampMixin, Base):
    """Restaurant KPIs from the last engine run; `restaurant_id` NULL is the network (revenue-weighted).

    Stored because a director may see the network's average but not the other restaurants' rows it comes from.
    """

    __tablename__ = "kpi_snapshots"

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    computed_on: Mapped[date] = mapped_column(Date)
    food_cost_from: Mapped[date | None] = mapped_column(Date)
    food_cost_to: Mapped[date | None] = mapped_column(Date)
    revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    food_cost_actual: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    food_cost_theory: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    write_offs_from: Mapped[date | None] = mapped_column(Date)
    write_offs_to: Mapped[date | None] = mapped_column(Date)
    write_offs_share: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))


class TrendPoint(IdMixin, TenantMixin, TimestampMixin, Base):
    """Found potential at the end of a week and the confirmed effect so far (restaurant NULL: network)."""

    __tablename__ = "trend_points"

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    week_end: Mapped[date] = mapped_column(Date)
    losses: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    potential: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    open_findings: Mapped[int]
    returned: Mapped[Decimal] = mapped_column(Numeric(14, 2))
