"""A conversation with the assistant through the model (docs/08, «Чат с AI-ассистентом»).

`converse` drives one question:
1. the question (with the finding it was asked from, if any) goes to the model with the user's tools;
2. while the model calls tools, they run under the user's rights (`tools.run`) and the results go back;
   each call is announced as a status, so the screen can say what the assistant is looking at;
3. the answer is checked: every number must be in the tools' results or the question (`verify`). Once, the
   model is asked to correct it; if numbers still do not match, the answer is not shown — the caller answers
   by rules instead (`Final.verified = False`).

It is a generator of `Status` and, last, one `Final`: the chat endpoint streams them (SSE) or waits for the
last one. The conversation is kept in `chat_threads`/`chat_messages` (`app/ai/history.py`) as the model saw
it, append-only, so the next question continues it.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.ai import prompt as prompts
from app.ai import tools
from app.ai.gateway import Gateway, Message
from app.ai.verify import unsupported
from app.tenancy.context import AccessContext

MAX_ROUNDS = 6  # model calls per question: tool rounds and one correction
TOOL_STATUS = {
    "get_kpis": "Смотрю показатели",
    "get_findings": "Смотрю находки",
    "explain_finding": "Разбираю находку",
    "compare_restaurants": "Сравниваю рестораны",
    "get_tasks": "Смотрю задачи",
    "get_checks": "Смотрю проверки",
    "search_products": "Ищу товар",
    "get_purchase_prices": "Смотрю цены закупок",
}
REFUSED = "На этот вопрос я не отвечу. Спросите о показателях, находках, закупках или задачах ресторана."
TOO_LONG = "Ответ получился слишком длинным. Уточните вопрос — например, ресторан, товар или период."
CORRECT = (
    "Проверка ответа: числа {numbers} не найдены в результатах инструментов. Исправь ответ: используй только "
    "числа из результатов инструментов, ничего не считай сам. Если нужной цифры нет — так и скажи."
)


@dataclass(frozen=True)
class Status:
    text: str


@dataclass
class Final:
    text: str
    verified: bool
    finding_ids: list[UUID] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    new_messages: list[Message] = field(default_factory=list)  # to append to the conversation


def question_message(question: str, finding_id: UUID | None) -> Message:
    text = question if finding_id is None else f"[Вопрос задан из находки {finding_id}]\n{question}"
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def converse(
    gateway: Gateway,
    ctx: AccessContext,
    *,
    history: list[Message],
    question: str,
    finding_id: UUID | None,
    today: date,
) -> Iterator[Status | Final]:
    chat = prompts.load("chat")
    schemas = tools.schemas(ctx)
    new: list[Message] = [question_message(question, finding_id)]
    sources: list[Any] = [question]
    used: list[str] = []
    found: list[UUID] = [finding_id] if finding_id else []
    corrected = False
    bad: list[str] = []

    for _ in range(MAX_ROUNDS):
        reply = gateway.complete(ctx, task="chat", prompt=chat, messages=history + new, tools=schemas)
        new.append({"role": "assistant", "content": reply.content})
        if reply.stop_reason == "refusal":
            yield Final(REFUSED, True, found, used, [], new)
            return
        if reply.stop_reason == "max_tokens":
            yield Final(TOO_LONG, True, found, used, [], new)
            return
        if reply.tool_calls:
            results = []
            for call in reply.tool_calls:
                name = call.get("name", "")
                yield Status(TOOL_STATUS.get(name, "Смотрю данные"))
                result, is_error = tools.run(
                    name, call.get("input"), user_id=ctx.user_id, tenant_id=ctx.tenant_id, today=today
                )
                used.append(name)
                sources.append(result)
                if name == "explain_finding" and not is_error:
                    found.append(UUID(result["id"]))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                        "is_error": is_error,
                    }
                )
            new.append({"role": "user", "content": results})
            continue
        bad = unsupported(reply.text, sources)
        if not bad:
            yield Final(reply.text.strip(), True, list(dict.fromkeys(found)), used, [], new)
            return
        if corrected:
            break
        corrected = True
        yield Status("Сверяю цифры")
        new.append(
            {"role": "user", "content": [{"type": "text", "text": CORRECT.format(numbers=", ".join(bad))}]}
        )
    yield Final("", False, list(dict.fromkeys(found)), used, bad, new)
