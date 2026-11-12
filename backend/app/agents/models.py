from datetime import date, datetime
from enum import StrEnum
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


class Agent(StrEnum):
    INVENTORY_PREP = "inventory_prep"  # № 1: what to count carefully before the next stock count
    TASK_DUE = "task_due"  # № 7: a task's deadline is near (to the director)
    TASK_STUCK = "task_stuck"  # № 7: a task is late and not started (to the HQ: move the deadline?)
    DATA_CHECK = "data_check"  # № 9: which exports are missing this morning
    SHORTAGE_STORY = "shortage_story"  # № 2: a large shortage's timeline and versions (to the HQ's analyst)
    SUPPLIER_CLAIM = "supplier_claim"  # № 3: a claim or a request to a supplier about prices (to the HQ)
    TRANSFER = "transfer"  # № 5: move stock from a restaurant that has it to one that runs out (to the HQ)
    HQ_AGENDA = "hq_agenda"  # № 8: the agenda of the HQ's weekly meeting (the network, no restaurant)


class Audience(StrEnum):
    DIRECTOR = "director"
    HQ = "hq"


class NoteStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"  # «Создать задачу»: the proposal was carried out
    DISMISSED = "dismissed"  # «Не нужно»
    EXPIRED = "expired"  # the reason went away before anyone decided


AGENTS = tuple(a.value for a in Agent)
STATUSES = tuple(s.value for s in NoteStatus)


class AgentNote(IdMixin, TenantMixin, Base):
    """One message of an agent to the director of a restaurant or to the HQ (ADR 0010).

    `facts` is what the code computed; `title`, `text` and `items` are shown — by the model when every number
    of its text matched the facts, by rules otherwise (`source`). `proposal` is what «Создать задачу» does.
    One per agent and reason (`key`): running the agent again refreshes a new note and leaves a decided one.
    Seen under the restaurant's row-level security; notes to the HQ — by the HQ only (migration 0032).
    """

    __tablename__ = "agent_notes"
    __table_args__ = (
        CheckConstraint(f"agent IN {AGENTS}", name="agent_valid"),
        CheckConstraint("audience IN ('director', 'hq')", name="audience_valid"),
        CheckConstraint(f"status IN {STATUSES}", name="status_valid"),
        CheckConstraint("source IN ('rules', 'model')", name="source_valid"),
        # A note about the whole network (the weekly agenda) is the HQ's: no director sees it (0034).
        CheckConstraint("restaurant_id IS NOT NULL OR audience = 'hq'", name="network_notes_to_hq"),
        UniqueConstraint("tenant_id", "agent", "key"),
    )

    restaurant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(30))
    audience: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(200))
    for_date: Mapped[date] = mapped_column(
        Date
    )  # the day the reason is about: the count, the deadline, today
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    title: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    items: Mapped[list[str]] = mapped_column(JSONB)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(10))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default=NoteStatus.NEW, server_default="new")
    created_on: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
