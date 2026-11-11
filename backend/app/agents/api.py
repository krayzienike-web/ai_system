"""The agents' notes (stage 9, ADR 0010): what waits for an answer, and the answers."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import service
from app.agents.models import AgentNote
from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

router = APIRouter(tags=["agents"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class NoteOut(BaseModel):
    id: UUID
    agent: Literal["inventory_prep", "task_due", "task_stuck", "data_check"]
    audience: Literal["director", "hq"]
    restaurant_id: UUID
    restaurant_code: str
    restaurant_name: str
    for_date: date
    task_id: UUID | None
    title: str
    text: str
    items: list[str]
    # What «Создать задачу» does: «create_task» (a task with the list), «move_due» (a new deadline), none.
    action: Literal["create_task", "move_due"] | None
    action_due_on: date | None
    action_title: str | None  # the task «Создать задачу» makes
    source: Literal["rules", "model"]
    status: Literal["new", "accepted", "dismissed", "expired"]
    result_task_id: UUID | None


def notes_out(session: Session, notes: list[AgentNote]) -> list[NoteOut]:
    ids = {n.restaurant_id for n in notes}
    places = {r.id: r for r in session.execute(select(Restaurant).where(Restaurant.id.in_(ids))).scalars()}
    out = []
    for n in notes:
        proposal: dict[str, Any] = n.proposal or {}
        r = places[n.restaurant_id]
        out.append(
            NoteOut(
                id=n.id,
                agent=n.agent,
                audience=n.audience,
                restaurant_id=n.restaurant_id,
                restaurant_code=r.code,
                restaurant_name=r.name,
                for_date=n.for_date,
                task_id=n.task_id,
                title=n.title,
                text=n.text,
                items=n.items,
                action=proposal.get("action"),
                action_due_on=date.fromisoformat(proposal["due_on"]) if "due_on" in proposal else None,
                action_title=proposal.get("title"),
                source=n.source,
                status=n.status,
                result_task_id=n.result_task_id,
            )
        )
    return out


@router.get("/agents/notes")
def list_notes(ctx: CanRead, session: SessionDep, restaurant: UUID | None = None) -> list[NoteOut]:
    """The notes waiting for an answer. A director — those to the director of their restaurant; the HQ — all,
    or one restaurant's (`restaurant`)."""
    return notes_out(session, service.notes(session, ctx, restaurant))


@router.post("/agents/notes/{note_id}/accept")
def accept(note_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> NoteOut:
    """«Создать задачу»: a task from the list, or the deadline moved (the HQ admin)."""
    (out,) = notes_out(session, [service.accept(session, ctx, note_id, today=today)])
    session.commit()
    return out


@router.post("/agents/notes/{note_id}/dismiss")
def dismiss(note_id: UUID, ctx: CanRead, session: SessionDep) -> NoteOut:
    """«Не нужно»."""
    (out,) = notes_out(session, [service.dismiss(session, ctx, note_id)])
    session.commit()
    return out


class InventoryAsk(BaseModel):
    restaurant_id: UUID
    count_on: date


@router.post("/agents/inventory-prep")
def ask_inventory(body: InventoryAsk, ctx: CanRead, session: SessionDep, today: TodayDep) -> NoteOut:
    """The list «что пересчитать внимательно» for a count on a chosen day."""
    note = service.ask_inventory(session, ctx, body.restaurant_id, body.count_on, today=today)
    (out,) = notes_out(session, [note])
    session.commit()
    return out
