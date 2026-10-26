from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class ExperimentStatus(StrEnum):
    PROPOSED = "proposed"  # waiting for HQ to launch it
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"


class Verdict(StrEnum):
    CONFIRMED = "confirmed"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"


class Experiment(IdMixin, TenantMixin, TimestampMixin, Base):
    """A check of a change on part of the network.

    HQ launches it; launching sets tasks for the test restaurants.
    """

    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'running', 'completed', 'rejected')", name="status_valid"),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('confirmed', 'inconclusive', 'rejected')", name="verdict_valid"
        ),
        CheckConstraint("(status = 'completed') = (verdict IS NOT NULL)", name="verdict_when_completed"),
        CheckConstraint("ends_on > starts_on", name="ends_after_start"),
        CheckConstraint("cardinality(test_restaurant_ids) > 0", name="has_test_group"),
    )

    finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    hypothesis: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(300))
    test_restaurant_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)))
    control_restaurant_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)), default=list)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    expected_rub_month: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(
        String(20), default=ExperimentStatus.PROPOSED, server_default="proposed"
    )
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Result: written by the measurement (difference in differences), never typed by a person.
    verdict: Mapped[str | None] = mapped_column(String(20))
    effect_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ci_low_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ci_high_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    result_text: Mapped[str | None] = mapped_column(Text)
    completed_on: Mapped[date | None] = mapped_column(Date)
    baseline: Mapped[str | None] = mapped_column(Text)  # what the change is compared with, in words
    progress_text: Mapped[str | None] = mapped_column(Text)  # interim measurement, written by the measurement
    rollout_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # the effect network-wide
    rollout_on: Mapped[date | None] = mapped_column(Date)  # when HQ set the change for every restaurant
    proposed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
