from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin


class Digest(IdMixin, TenantMixin, Base):
    """One week's digest of a restaurant (or of the network: no restaurant), docs/08 part 1.

    `input` is what the code computed (`digests.builder`), `output` the texts shown — by the model when it
    is on and every number of them matched the input, by rules otherwise (`source`). One per restaurant and
    week (migration 0022): building again replaces it. Seen under the restaurant's row-level security; the
    network's — by the HQ only.
    """

    __tablename__ = "digests"
    __table_args__ = (CheckConstraint("source IN ('rules', 'model')", name="source_valid"),)

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)
    week_end: Mapped[date] = mapped_column(Date)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(10))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


REASONS = ("wrong_data", "explained", "already_fixed", "other")


class Disagreement(IdMixin, TenantMixin, Base):
    """A director's «Не согласен» with a finding of their restaurant (docs/08 part 1, stage 6): the reason
    and a comment, for the HQ to read. Not a dispute of a task (ADR 0006): the finding's facts are questioned,
    and the HQ decides. One per person and finding: saying it again replaces it."""

    __tablename__ = "disagreements"
    __table_args__ = (
        CheckConstraint(f"reason IN {REASONS}", name="reason_valid"),
        UniqueConstraint("finding_id", "user_id"),
    )

    restaurant_id: Mapped[UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    finding_id: Mapped[UUID] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    digest_id: Mapped[UUID | None] = mapped_column(ForeignKey("digests.id", ondelete="SET NULL"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
