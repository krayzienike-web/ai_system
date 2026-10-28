"""The one door to the language model (ADR 0005; CLAUDE.md: LLM only through `app/ai/gateway`).

Every call goes through `Gateway.complete`:
- the user's daily request budget is checked first (`ai_runs` of today, settings `ai_requests_per_user_day`);
- the model is called — the real one (`app/ai/claude.py`) or the scripted stand-in for tests (`FakeModel`);
- the call is written to `ai_runs`: prompt and version, model, request, response, tokens, cost, time — also
  when the model refused, ran out of tokens or failed.

The log and the budget use their own short transactions under the user's row-level security, so a failed
request does not lose its log entry and the caller's transaction is not touched.

Messages, tools and replies are kept in the Messages API's JSON shape: no translation layer for a second
provider (ADR 0005), and the log stores exactly what was sent.
"""

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.models import AiRun
from app.ai.prompt import Prompt
from app.core.config import get_settings
from app.core.db import apply_rls_context, get_sessionmaker
from app.core.errors import RuleError
from app.tenancy.context import AccessContext

Task = Literal["chat", "explain", "digest", "match"]
Message = dict[str, Any]
Tool = dict[str, Any]
Block = dict[str, Any]

MILLION = Decimal(1_000_000)
# USD per million tokens: input, output, cache read, cache write (5-minute). ADR 0005 picks the models.
PRICES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}


class BudgetError(RuleError):
    status_code = 429


class ModelUnavailableError(RuleError):
    """The model could not be reached or answered with an error; the caller falls back or says so."""

    status_code = 503


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    messages: Sequence[Message]
    tools: Sequence[Tool] = ()
    max_tokens: int = 16000


@dataclass(frozen=True)
class Reply:
    content: list[Block]
    stop_reason: str | None
    usage: Usage = Usage()
    model: str = ""

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_calls(self) -> list[Block]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class Model(Protocol):
    def complete(self, request: ModelRequest) -> Reply: ...


@dataclass
class FakeModel:
    """A scripted model for tests and for working without the API key (Q12): replies are given in advance,
    or computed from the request; every request is kept for the test to look at."""

    replies: list[Reply | Callable[[ModelRequest], Reply]] = field(default_factory=list)
    requests: list[ModelRequest] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> Reply:
        self.requests.append(request)
        if not self.replies:
            raise ModelUnavailableError("FakeModel: no reply scripted")
        reply = self.replies.pop(0)
        return reply(request) if callable(reply) else reply


def text_reply(text: str, *, usage: Usage = Usage(input_tokens=100, output_tokens=20)) -> Reply:
    return Reply([{"type": "text", "text": text}], "end_turn", usage)


def tool_reply(name: str, args: dict[str, Any], *, call_id: str = "call_1") -> Reply:
    return Reply(
        [{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        "tool_use",
        Usage(input_tokens=100, output_tokens=10),
    )


def cost_usd(model: str, usage: Usage) -> Decimal:
    if model not in PRICES:
        return Decimal("0")
    inp, out, read, write = PRICES[model]
    total = (
        usage.input_tokens * inp
        + usage.output_tokens * out
        + usage.cache_read_tokens * read
        + usage.cache_write_tokens * write
    )
    return (total / MILLION).quantize(Decimal("0.000001"))


STATUS = {"refusal": "refused", "max_tokens": "truncated"}


@contextmanager
def _as_user(ctx: AccessContext) -> Iterator[Session]:
    with get_sessionmaker()() as session, session.begin():
        apply_rls_context(session, ctx.to_rls())
        yield session


def used_today(ctx: AccessContext) -> int:
    with _as_user(ctx) as s:
        return s.execute(
            select(func.count())
            .select_from(AiRun)
            .where(AiRun.user_id == ctx.user_id, AiRun.created_at >= func.date_trunc("day", func.now()))
        ).scalar_one()


class Gateway:
    def __init__(self, model: Model, *, model_id: str | None = None, per_user_day: int | None = None) -> None:
        settings = get_settings()
        self.model = model
        self.model_id = model_id or settings.ai_model
        self.per_user_day = settings.ai_requests_per_user_day if per_user_day is None else per_user_day

    def complete(
        self,
        ctx: AccessContext,
        *,
        task: Task,
        prompt: Prompt,
        messages: Sequence[Message],
        tools: Sequence[Tool] = (),
    ) -> Reply:
        if used_today(ctx) >= self.per_user_day:
            raise BudgetError("Лимит вопросов ассистенту на сегодня исчерпан, он обновится завтра")
        request = ModelRequest(self.model_id, prompt.text, list(messages), list(tools))
        started = time.monotonic()
        try:
            reply = self.model.complete(request)
        except Exception as exc:
            self._log(ctx, task, prompt, request, None, started, error=f"{type(exc).__name__}: {exc}")
            if isinstance(exc, RuleError):
                raise
            raise ModelUnavailableError("Ассистент сейчас недоступен, попробуйте позже") from exc
        self._log(ctx, task, prompt, request, reply, started)
        return reply

    def _log(
        self,
        ctx: AccessContext,
        task: Task,
        prompt: Prompt,
        request: ModelRequest,
        reply: Reply | None,
        started: float,
        *,
        error: str | None = None,
    ) -> None:
        usage = reply.usage if reply else Usage()
        model = (reply.model if reply and reply.model else None) or request.model
        with _as_user(ctx) as s:
            s.add(
                AiRun(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    task=task,
                    prompt=prompt.name,
                    prompt_version=prompt.version,
                    model=model,
                    status="failed" if reply is None else STATUS.get(reply.stop_reason or "", "ok"),
                    stop_reason=reply.stop_reason if reply else None,
                    request={
                        "prompt_sha256": prompt.sha256,
                        "messages": list(request.messages),
                        "tools": [t["name"] for t in request.tools],
                    },
                    response=reply.content if reply else None,
                    error=error,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=cost_usd(model, usage),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            )


def get_model() -> Model | None:
    """The model this server talks to: `claude` (needs ANTHROPIC_API_KEY), or none — then the chat answers by
    its rules, as before stage 5."""
    settings = get_settings()
    if settings.ai_provider == "claude":
        from app.ai.claude import ClaudeModel

        return ClaudeModel()
    return None
