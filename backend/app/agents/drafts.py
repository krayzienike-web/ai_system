"""What an agent found: the reason, the facts the code computed and what «Создать задачу» would do."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.agents.models import Agent, Audience


@dataclass(frozen=True)
class NoteDraft:
    agent: Agent
    audience: Audience
    restaurant_id: UUID | None  # None: about the whole network (to the HQ only)
    key: str  # one note per agent and reason: running again finds the same key
    for_date: date
    facts: dict[str, Any]
    task_id: UUID | None = None
    proposal: dict[str, Any] | None = field(default=None)
