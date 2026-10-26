from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class FindingKind(StrEnum):
    PROBLEM = "problem"  # losing money against a norm
    OPPORTUNITY = "opportunity"  # no norm broken, but more can be earned


class ReviewStatus(StrEnum):
    PENDING = "pending"  # waits for HQ to check it against the data
    CONFIRMED = "confirmed"  # visible to the restaurant
    REJECTED = "rejected"  # wrong: kept with the reason, hidden from everyone but the review page


class FindingStatus(StrEnum):
    NEW = "new"
    IN_WORK = "in_work"
    IN_EXPERIMENT = "in_experiment"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Finding(IdMixin, TenantMixin, TimestampMixin, Base):
    """What the analytics engine found.

    A finding without a restaurant is network-wide and visible to HQ only.
    """

    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("kind IN ('problem', 'opportunity')", name="kind_valid"),
        CheckConstraint(
            "status IN ('new', 'in_work', 'in_experiment', 'resolved', 'dismissed')", name="status_valid"
        ),
        CheckConstraint("resolved_on IS NULL OR resolved_on >= found_on", name="resolved_after_found"),
    )

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    process: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    headline: Mapped[str | None] = mapped_column(Text)
    # Effect in rubles per month; null when it cannot be estimated yet (then effect_note explains why).
    effect_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    effect_note: Mapped[str | None] = mapped_column(String(300))
    actions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), default=FindingStatus.NEW, server_default="new")
    found_on: Mapped[date] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    algorithm_version: Mapped[str] = mapped_column(String(50), default="manual", server_default="manual")
    # Written by the analytics engine (null for findings made by hand). The same problem keeps the same key
    # between runs, so a re-run updates the numbers and keeps the work on it (docs/12-analytics-engine.md).
    key: Mapped[str | None] = mapped_column(String(200))
    module: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[str | None] = mapped_column(String(10))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Manual review of engine findings (docs/12): pending → confirmed | rejected.
    # Directors see only confirmed ones (row-level security).
    review_status: Mapped[str | None] = mapped_column(String(20))
    review_reason: Mapped[str | None] = mapped_column(
        String(30)
    )  # why rejected: data | logic | false_alarm | other
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_on: Mapped[date | None] = mapped_column(Date)
