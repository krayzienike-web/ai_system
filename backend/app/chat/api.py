from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.chat import service
from app.core.deps import SessionDep, require
from app.core.period import TodayDep
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["chat"])

CanChat = Annotated[AccessContext, Depends(require(Permission.AI_CHAT))]


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    finding_id: UUID | None = None


class AnswerOut(BaseModel):
    text: str
    columns: list[str]
    rows: list[list[str]]
    source_finding_id: UUID | None
    source: str | None
    suggestions: list[str]


@router.get("/chat/suggestions")
def chat_suggestions(ctx: CanChat) -> list[str]:
    return service.suggestions(ctx)


@router.post("/chat")
def ask(body: AskIn, ctx: CanChat, session: SessionDep, today: TodayDep) -> AnswerOut:
    a = service.answer(session, ctx, body.question, today, body.finding_id)
    return AnswerOut(**a.__dict__)
