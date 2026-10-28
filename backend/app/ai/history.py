"""Conversations with the assistant, kept per person (`chat_threads`, `chat_messages`; migration 0017).

Short transactions of their own under the user's row-level security: the model call between reading and
writing may take seconds, and no request transaction stays open meanwhile. Messages are only added, never
edited, so a conversation replays to the model exactly as it went.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import Message
from app.ai.models import ChatMessage, ChatThread
from app.core.errors import NotFoundError
from app.tenancy.context import AccessContext, user_session

KEEP = 40  # messages replayed to the model: the last ones, starting at a question


@dataclass(frozen=True)
class ThreadInfo:
    id: UUID
    title: str
    finding_id: UUID | None
    updated_at: datetime


@dataclass(frozen=True)
class Line:
    role: str
    text: str
    at: datetime


def _thread(session: Session, thread_id: UUID, *, lock: bool = False) -> ChatThread:
    # Another person's thread is not visible, so not found. `lock`: two questions to one thread at once
    # (a double click, a second tab) append one after the other (code review 28.10.2026, stage 5, p. 8).
    thread = session.get(ChatThread, thread_id, with_for_update=lock)
    if thread is None:
        raise NotFoundError("Разговор не найден")
    return thread


def start(ctx: AccessContext, *, title: str, finding_id: UUID | None) -> UUID:
    with user_session(ctx) as s:
        thread = ChatThread(
            tenant_id=ctx.tenant_id, user_id=ctx.user_id, title=title[:200], finding_id=finding_id
        )
        s.add(thread)
        s.flush()
        return thread.id


def replay(ctx: AccessContext, thread_id: UUID) -> list[Message]:
    """The conversation as the model saw it; a long one is cut at a question, so tool calls keep their
    results."""
    with user_session(ctx) as s:
        _thread(s, thread_id)
        rows = list(
            s.execute(
                select(ChatMessage).where(ChatMessage.thread_id == thread_id).order_by(ChatMessage.seq)
            ).scalars()
        )
    messages = [{"role": m.role, "content": m.content} for m in rows]
    if len(rows) > KEEP:
        starts = [
            i for i, m in enumerate(rows) if m.role == "user" and m.text is not None and i >= len(rows) - KEEP
        ]
        messages = messages[starts[0] :] if starts else []
    return messages


def append(
    ctx: AccessContext, thread_id: UUID, messages: list[Message], *, question: str, answer: str | None
) -> None:
    """The messages of one question; the first is the question, the last assistant one carries the answer
    shown to the person."""
    last_assistant = max((i for i, m in enumerate(messages) if m["role"] == "assistant"), default=None)
    with user_session(ctx) as s:
        thread = _thread(s, thread_id, lock=True)
        seq = s.execute(
            select(func.coalesce(func.max(ChatMessage.seq), 0)).where(ChatMessage.thread_id == thread_id)
        ).scalar_one()
        for i, m in enumerate(messages):
            text = question if i == 0 else (answer if i == last_assistant else None)
            s.add(
                ChatMessage(
                    tenant_id=ctx.tenant_id,
                    thread_id=thread_id,
                    user_id=ctx.user_id,
                    seq=seq + i + 1,
                    role=m["role"],
                    content=m["content"],
                    text=text,
                )
            )
        thread.updated_at = func.now()


def threads(ctx: AccessContext) -> list[ThreadInfo]:
    with user_session(ctx) as s:
        rows = s.execute(select(ChatThread).order_by(ChatThread.updated_at.desc()).limit(50)).scalars()
        return [ThreadInfo(t.id, t.title, t.finding_id, t.updated_at) for t in rows]


def lines(ctx: AccessContext, thread_id: UUID) -> list[Line]:
    """What the person sees: their questions and the checked answers."""
    with user_session(ctx) as s:
        _thread(s, thread_id)
        rows = s.execute(
            select(ChatMessage.role, ChatMessage.text, ChatMessage.created_at)
            .where(ChatMessage.thread_id == thread_id, ChatMessage.text.is_not(None))
            .order_by(ChatMessage.seq)
        ).all()
        return [Line(r, t or "", at) for r, t, at in rows]
