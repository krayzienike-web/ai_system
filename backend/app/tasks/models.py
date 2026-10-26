from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class TaskStatus(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    # "Overdue" is not stored: it is derived from due_on and today.


class AssignedBy(StrEnum):
    HQ = "hq"
    DIRECTOR = "director"


class OutcomeVerdict(StrEnum):
    PENDING = "pending"  # done, result measured after the next recount
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"


class Task(IdMixin, TenantMixin, TimestampMixin, Base):
    """Work in one restaurant, traced from the finding to the measured result (ADR 0006).

    The report is written by the director; the outcome is written only by the analytics layer.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('assigned', 'in_progress', 'done')", name="status_valid"),
        CheckConstraint("assigned_by IN ('hq', 'director')", name="assigned_by_valid"),
        CheckConstraint(
            "outcome_verdict IS NULL OR outcome_verdict IN ('pending', 'confirmed', 'not_confirmed')",
            name="outcome_valid",
        ),
        CheckConstraint("(status = 'done') = (done_on IS NOT NULL)", name="done_has_date"),
        CheckConstraint("status = 'done' OR outcome_verdict IS NULL", name="outcome_only_when_done"),
        CheckConstraint("due_on >= created_on", name="due_after_created"),
        Index("ix_tasks_restaurant_status", "restaurant_id", "status"),
    )

    restaurant_id: Mapped[UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"), index=True
    )
    experiment_id: Mapped[UUID | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    checklist: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Which checklist steps the director has ticked (same length as `checklist`).
    checklist_done: Mapped[list[bool]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    reminded_on: Mapped[date | None] = mapped_column(Date)  # HQ's last reminder about an overdue task
    assigned_by: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.ASSIGNED, server_default="assigned")
    done_on: Mapped[date | None] = mapped_column(Date)
    report: Mapped[str | None] = mapped_column(Text)
    outcome_verdict: Mapped[str | None] = mapped_column(String(20))
    outcome_effect_rub_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outcome_text: Mapped[str | None] = mapped_column(Text)
    outcome_measured_on: Mapped[date | None] = mapped_column(Date)
