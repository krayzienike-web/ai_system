from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin

RUN_STATUSES = ("ok", "refused", "truncated", "failed")


class AiRun(IdMixin, TenantMixin, Base):
    """One call to the model (docs/03-architecture.md, «AiRun лог»): what was asked, with which prompt and
    model, what came back, the tokens, the cost and the time. The application may only add rows (migration
    0016), so the log is also the base of the request budget."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status_valid"),
        Index("ix_ai_runs_tenant_user_created", "tenant_id", "user_id", "created_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task: Mapped[str] = mapped_column(String(30))  # chat | explain | digest | match
    prompt: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response: Mapped[list[Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
