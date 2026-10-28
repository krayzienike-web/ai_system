import json
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai import history
from app.ai.gateway import Gateway, get_gateway
from app.chat import service
from app.chat.assistant import Done, respond
from app.core.deps import require
from app.core.errors import RuleError
from app.core.period import TodayDep
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["chat"])

CanChat = Annotated[AccessContext, Depends(require(Permission.AI_CHAT))]
GatewayDep = Annotated[Gateway | None, Depends(get_gateway)]


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    finding_id: UUID | None = None
    thread_id: UUID | None = None  # continue this conversation


class AnswerOut(BaseModel):
    text: str
    columns: list[str]
    rows: list[list[str]]
    source_finding_id: UUID | None
    source: str | None
    suggestions: list[str]
    thread_id: UUID | None = None


class ThreadOut(BaseModel):
    id: UUID
    title: str
    finding_id: UUID | None
    updated_at: datetime


class LineOut(BaseModel):
    role: str
    text: str
    at: datetime


def _out(done: Done) -> AnswerOut:
    return AnswerOut(**done.answer.__dict__, thread_id=done.thread_id)


@router.get("/chat/suggestions")
def chat_suggestions(ctx: CanChat) -> list[str]:
    return service.suggestions(ctx)


@router.post("/chat")
def ask(body: AskIn, ctx: CanChat, gateway: GatewayDep, today: TodayDep) -> AnswerOut:
    events = respond(
        gateway,
        ctx,
        question=body.question,
        finding_id=body.finding_id,
        thread_id=body.thread_id,
        today=today,
    )
    done = [e for e in events if isinstance(e, Done)][-1]
    return _out(done)


@router.post("/chat/stream")
def ask_streaming(body: AskIn, ctx: CanChat, gateway: GatewayDep, today: TodayDep) -> StreamingResponse:
    """The same answer as Server-Sent Events: `status` while the assistant looks at the data, then `answer`
    (or `error` with the message and the HTTP status it would have had)."""

    def events() -> Iterator[str]:
        try:
            for e in respond(
                gateway,
                ctx,
                question=body.question,
                finding_id=body.finding_id,
                thread_id=body.thread_id,
                today=today,
            ):
                if isinstance(e, Done):
                    yield f"event: answer\ndata: {_out(e).model_dump_json()}\n\n"
                else:
                    yield f"event: status\ndata: {json.dumps({'text': e.text}, ensure_ascii=False)}\n\n"
        except RuleError as exc:
            error = {"detail": str(exc), "status": exc.status_code}
            yield f"event: error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/chat/threads")
def chat_threads(ctx: CanChat) -> list[ThreadOut]:
    return [ThreadOut(**t.__dict__) for t in history.threads(ctx)]


@router.get("/chat/threads/{thread_id}")
def chat_thread(thread_id: UUID, ctx: CanChat) -> list[LineOut]:
    return [LineOut(**line.__dict__) for line in history.lines(ctx, thread_id)]
