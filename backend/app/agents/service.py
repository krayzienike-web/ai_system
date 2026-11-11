"""Running the agents and answering their notes (stage 9, ADR 0010).

`run` is the morning pass of one network under the system's scope: each agent finds its reasons, a note is
written per reason (`key`) — a new one, or the same note refreshed while nobody has decided on it; a note
nobody decided on whose reason is gone expires. Safe to run again: the same day gives the same notes.

A person answers a note: «Создать задачу» does what it proposes (a task from the list, a moved deadline),
«Не нужно» puts it away. Nothing happens without that.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.agents import data, deadlines, inventory, texts
from app.agents.drafts import NoteDraft
from app.agents.models import Agent, AgentNote, Audience, NoteStatus
from app.core.db import get_sessionmaker
from app.core.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from app.tasks import service as tasks
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext, system_context
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

log = logging.getLogger(__name__)

# The model's text of a note: (agent, facts, the rules' text) → (text, prompt version); None: the rules.
Writer = Callable[[str, dict[str, Any], str], tuple[str, int] | None]

ASK_AHEAD_DAYS = 14  # a list asked for by hand: for a count up to two weeks ahead


@dataclass(frozen=True)
class Text:
    title: str
    text: str
    items: list[str]
    source: str = "rules"
    prompt_version: int | None = None


def _text(d: NoteDraft, write: Writer | None) -> Text:
    """The note in words: by rules, the text by the model when it is on and passes the check."""
    title, body, items = texts.by_rules(d.agent, d.facts)
    if write is None:
        return Text(title, body, items)
    try:
        written = write(d.agent, d.facts, body)
    except Exception:  # the model must never cost the note: the rules' text stays
        log.exception("the model's text of an agent's note failed")
        written = None
    if written is None:
        return Text(title, body, items)
    return Text(title, written[0], items, "model", written[1])


def _apply(note: AgentNote, d: NoteDraft, t: Text) -> None:
    note.facts, note.proposal = d.facts, d.proposal
    note.title, note.text, note.items = t.title, t.text, t.items
    note.source, note.prompt_version = t.source, t.prompt_version
    note.updated_at = datetime.now(UTC)


def _existing(session: Session, d: NoteDraft, *, lock: bool) -> AgentNote | None:
    q = select(AgentNote).where(AgentNote.agent == d.agent, AgentNote.key == d.key)
    return session.execute(q.with_for_update() if lock else q).scalar_one_or_none()


def _save(
    session: Session, tenant_id: UUID, d: NoteDraft, today: date, t: Text | None, *, reopen: bool = False
) -> AgentNote:
    """The note of this reason: inserted, or refreshed while nobody has decided on it. `t` None — the facts
    did not change, the text stays. `reopen` (a list asked for again): an expired or dismissed note is new
    again; one already taken into work is refused.

    The row is inserted with ON CONFLICT DO NOTHING and then locked: two writers of the same reason at once
    (a double click, the morning run and a person) meet on the row, not on the unique key (backend review of
    stage 9, p. 4)."""
    session.execute(
        insert(AgentNote)
        .values(
            tenant_id=tenant_id,
            restaurant_id=d.restaurant_id,
            agent=d.agent,
            audience=d.audience,
            key=d.key,
            for_date=d.for_date,
            task_id=d.task_id,
            facts=d.facts,
            proposal=d.proposal,
            title="",
            text="",
            items=[],
            source="rules",
            status=NoteStatus.NEW,
            created_on=today,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "agent", "key"])
    )
    note = _existing(session, d, lock=True)
    assert note is not None
    session.refresh(note)
    fresh = note.title == ""  # just inserted, by this statement or a concurrent one
    if reopen and note.status == NoteStatus.ACCEPTED:
        raise ConflictError("Список на этот день уже стал задачей — она в «Задачах»")
    if reopen and note.status in (NoteStatus.EXPIRED, NoteStatus.DISMISSED):
        note.status, note.decided_by, note.decided_at = NoteStatus.NEW, None, None
        fresh = True
    if note.status == NoteStatus.NEW and (fresh or note.facts != d.facts):
        _apply(note, d, t if t is not None else _text(d, None))
    session.flush()
    return note


AUTOMATIC = (Agent.INVENTORY_PREP, Agent.TASK_DUE, Agent.TASK_STUCK, Agent.DATA_CHECK)
LOCK_TIMEOUT = "10s"  # a person's answer holds a note's row for a moment; the run does not wait longer


def _asked_again(session: Session, today: date) -> list[NoteDraft]:
    """The lists asked for by hand whose day has not come: computed again, so «через 2 дня» stays true
    (backend review of stage 9, p. 3)."""
    out = []
    for note in session.execute(
        select(AgentNote).where(
            AgentNote.status == NoteStatus.NEW,
            AgentNote.agent == Agent.INVENTORY_PREP,
            AgentNote.for_date >= today,
        )
    ).scalars():
        if not note.facts.get("asked"):
            continue
        restaurant = session.get(Restaurant, note.restaurant_id)
        d = inventory.prepare(session, restaurant, note.for_date, today) if restaurant else None
        if d is not None:
            out.append(replace(d, facts={**d.facts, "asked": True}))
    return out


def run_network(session: Session, tenant_id: UUID, today: date, write: Writer | None = None) -> int:
    """One network's pass; the caller commits. Returns how many notes are new or refreshed and waiting.

    One pass of a network at a time (an advisory lock: the worker and `run-agents` do not collide). The
    model writes first, with no row locked; the notes are then written in one short stretch, so a director
    answering during the pass waits a moment, not for the model (backend review of stage 9, p. 1)."""
    system_context(session, tenant_id)
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext('agents:' || :t))"), {"t": str(tenant_id)})
    restaurants = list(session.execute(select(Restaurant).order_by(Restaurant.code)).scalars())
    drafts = {
        (d.agent, d.key): d
        for d in _asked_again(session, today)
        + inventory.drafts(session, restaurants, today)
        + deadlines.drafts(session, restaurants, today)
        + data.drafts(session, restaurants, today)
    }
    written: dict[tuple[str, str], Text | None] = {}
    for k, d in drafts.items():
        old = _existing(session, d, lock=False)
        changed = old is None or (old.status == NoteStatus.NEW and old.facts != d.facts)
        written[k] = _text(d, write) if changed else None
    keep = [_save(session, tenant_id, d, today, written[k]).id for k, d in drafts.items()]
    # What nobody decided on and no agent found again has expired; a decision made meanwhile stays (p. 5).
    session.execute(
        update(AgentNote)
        .where(
            AgentNote.status == NoteStatus.NEW,
            AgentNote.agent.in_(AUTOMATIC),
            AgentNote.id.not_in(keep) if keep else true(),
        )
        .values(status=NoteStatus.EXPIRED, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    session.flush()
    return len(keep)


def run_all(today: date, write_for: Callable[[AccessContext], Writer | None] | None = None) -> int:
    """Every network, each in a transaction of its own: one network's failure does not stop the others."""
    with get_sessionmaker()() as session:
        tenants = list(session.execute(text("SELECT app.tenant_ids()")).scalars())
    total = 0
    for tenant_id in tenants:
        try:
            with get_sessionmaker()() as session:
                write = write_for(system_context(session, tenant_id)) if write_for else None
                total += run_network(session, tenant_id, today, write)
                session.commit()
        except Exception:
            log.exception("the agents of network %s failed", tenant_id)
    return total


def notes(session: Session, ctx: AccessContext, restaurant_id: UUID | None = None) -> list[AgentNote]:
    """The notes waiting for an answer, as this person may see them (row-level security: a director — the
    notes to the director of their restaurant; the HQ — all)."""
    q = select(AgentNote).where(AgentNote.status == NoteStatus.NEW)
    if restaurant_id is not None:
        q = q.where(AgentNote.restaurant_id == restaurant_id)
    return list(
        session.execute(q.order_by(AgentNote.for_date, AgentNote.created_on, AgentNote.key)).scalars()
    )


def _note(session: Session, note_id: UUID) -> AgentNote:
    note = session.get(AgentNote, note_id, with_for_update=True)
    if note is None:
        raise NotFoundError("Сообщение не найдено")
    if note.status != NoteStatus.NEW:
        raise ConflictError("По этому сообщению уже решили")
    return note


def _may_answer(ctx: AccessContext, note: AgentNote) -> None:
    if ctx.can(Permission.TASKS_ASSIGN):
        return
    if note.audience == Audience.DIRECTOR and ctx.can(Permission.TASKS_EXECUTE):
        return
    raise ForbiddenError("Отвечать на это сообщение может директор ресторана или администратор УК")


def _decided(session: Session, ctx: AccessContext, note: AgentNote, status: NoteStatus) -> None:
    note.status = status
    note.decided_by = ctx.user_id
    note.decided_at = datetime.now(UTC)
    note.updated_at = note.decided_at
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action=f"agent_note.{status}",
        entity="agent_note",
        entity_id=note.id,
        payload={"agent": note.agent, "result_task_id": note.result_task_id and str(note.result_task_id)},
    )


def accept(session: Session, ctx: AccessContext, note_id: UUID, *, today: date) -> AgentNote:
    """«Создать задачу»: what the note proposes, done by this person."""
    note = _note(session, note_id)
    _may_answer(ctx, note)
    action = (note.proposal or {}).get("action")
    if action == "create_task":
        proposal = note.proposal or {}
        due = date.fromisoformat(proposal["due_on"])
        if due < today:
            raise InvalidError("День пересчета уже прошел")
        (task,) = tasks.create_tasks(
            session,
            ctx,
            title=proposal["title"],
            due_on=due,
            today=today,
            restaurant_ids=[note.restaurant_id],
            checklist=[f"Пересчитать: {line}" for line in note.items],
        )
        note.result_task_id = task.id
    elif action == "move_due":
        if note.task_id is None:
            raise InvalidError("Задачи больше нет")
        due = date.fromisoformat((note.proposal or {})["due_on"])
        tasks.move_due(session, ctx, note.task_id, due, today=today)
        note.result_task_id = note.task_id
    else:
        raise InvalidError("Здесь нечего брать в работу: сообщение можно только скрыть")
    _decided(session, ctx, note, NoteStatus.ACCEPTED)
    return note


def dismiss(session: Session, ctx: AccessContext, note_id: UUID) -> AgentNote:
    """«Не нужно» (or «Скрыть» for a note that proposes nothing)."""
    note = _note(session, note_id)
    _may_answer(ctx, note)
    _decided(session, ctx, note, NoteStatus.DISMISSED)
    return note


def ask_inventory(
    session: Session, ctx: AccessContext, restaurant_id: UUID, count_on: date, *, today: date
) -> AgentNote:
    """A list for a count on a chosen day, asked for by the director or the HQ admin (the count is not where
    the usual interval puts it). Written by rules at once; every morning until its day the list is computed
    again (`_asked_again`), and then the model may write its text. Asked again after it expired or was put
    away — the same note, new again."""
    if not (ctx.can(Permission.TASKS_ASSIGN) or ctx.can(Permission.TASKS_EXECUTE)):
        raise ForbiddenError("Список готовит директор ресторана или администратор УК")
    if not today <= count_on <= today + timedelta(days=ASK_AHEAD_DAYS):
        raise InvalidError(f"День пересчета — с сегодня и не дальше {ASK_AHEAD_DAYS} дней")
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Ресторан не найден")
    if not inventory.count_days(session).get(restaurant.id):
        raise InvalidError("Не по чему готовить список: в ресторане еще не было инвентаризации")
    d = inventory.prepare(session, restaurant, count_on, today)
    if d is None:
        raise InvalidError(
            "Подсказать нечего: на прошлом пересчете нет товаров с ценой закупки и открытых находок"
        )
    d = replace(d, facts={**d.facts, "asked": True})
    return _save(session, ctx.tenant_id, d, today, None, reopen=True)
