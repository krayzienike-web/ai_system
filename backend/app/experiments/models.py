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
        CheckConstraint("design IN ('restaurants', 'items', 'before_after')", name="design_valid"),
        CheckConstraint(
            "metric_kind IS NULL OR metric_kind IN ('overuse', 'writeoffs', 'price', 'discounts', 'voids')",
            name="metric_kind_valid",
        ),
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
    # What the measurement measures and how (stage 7, docs/05 «Замер»): fixed when the check is proposed and
    # never changed after the launch. No metric: a change that is not measured by a check (a task only).
    design: Mapped[str] = mapped_column(String(20), default="restaurants", server_default="restaurants")
    metric_kind: Mapped[str | None] = mapped_column(String(20))  # overuse writeoffs price discounts voids
    metric_product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    metric_cashier: Mapped[str | None] = mapped_column(String(100))
    control_product_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), default=list, server_default="{}"
    )  # the «items» design: other products of the category in the test restaurant
    baseline_from: Mapped[date | None] = mapped_column(Date)
    baseline_to: Mapped[date | None] = mapped_column(Date)
    mde_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # the smallest effect it would see
    measured_on: Mapped[date | None] = mapped_column(Date)  # the last measurement (interim or final)
