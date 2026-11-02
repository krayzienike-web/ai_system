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
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))  # empty: a model without a price
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatThread(IdMixin, TenantMixin, Base):
    """A conversation with the assistant. Personal: only its author reads it, the HQ too (migration 0017)."""

    __tablename__ = "chat_threads"
    __table_args__ = (Index("ix_chat_threads_tenant_user_updated", "tenant_id", "user_id", "updated_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    finding_id: Mapped[UUID | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(IdMixin, TenantMixin, Base):
    """One message of a conversation as the model saw it (Messages API blocks: text, tool calls and results,
    thinking), so the conversation goes on exactly where it stopped; `text` is what the person sees."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
        Index("ix_chat_messages_thread_seq", "thread_id", "seq", unique=True),
    )

    thread_id: Mapped[UUID] = mapped_column(ForeignKey("chat_threads.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[Any] = mapped_column(JSONB)
    text: Mapped[str | None] = mapped_column(Text)  # shown in the chat: the question or the checked answer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


SUGGESTION_KINDS = ("hypotheses", "precheck", "finding_idea", "mapping")
SUGGESTION_STATUSES = ("proposed", "accepted", "rejected", "superseded")


class AiSuggestion(IdMixin, TenantMixin, Base):
    """A proposal of the assistant (ADR 0008): the AI proposes, the code checks, a person decides.

    `basis` is what the proposal was made from — the facts the code gathered — so the screen can show it
    next to the proposal; `content` is the proposal itself, validated against its schema and with every number
    checked against `basis`. Only a person sets `status` to accepted or rejected. A proposal about one
    restaurant carries `restaurant_id` and is seen under that restaurant's row-level security; about the
    network — by the HQ only (migration 0019)."""

    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint(f"kind IN {SUGGESTION_KINDS}", name="kind_valid"),
        CheckConstraint(f"status IN {SUGGESTION_STATUSES}", name="status_valid"),
        Index("ix_ai_suggestions_tenant_subject", "tenant_id", "kind", "subject_id"),
    )

    kind: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[UUID | None]  # the finding, the import batch; none for the network's ideas
    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    basis: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prompt: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
