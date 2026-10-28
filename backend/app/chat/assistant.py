"""«Спросить су-шефа» through the model when it is on, by rules when it is off (ADR 0005; docs/08).

One question → a stream of events: what the assistant is looking at (`Progress`) and the answer (`Done`).
The model's answer is shown only when every number in it matched the data (`app/ai/verify.py`); otherwise,
and when the model cannot be reached, the answer by rules is shown — a person never waits for nothing and
never sees an unchecked figure.

Questions to the model are kept as conversations (`app/ai/history.py`); answers by rules are not — they
carry no context to continue.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.ai import history
from app.ai.chat import Final, Status, converse
from app.ai.gateway import Gateway, ModelUnavailableError
from app.chat import service
from app.chat.service import Answer
from app.core.errors import NotFoundError
from app.insights.visible import visible_finding
from app.tenancy.context import AccessContext, user_session

CHECKED = "Ответ ИИ: цифры сверены с данными"


@dataclass(frozen=True)
class Progress:
    text: str


@dataclass(frozen=True)
class Done:
    answer: Answer
    thread_id: UUID | None


def _by_rules(ctx: AccessContext, question: str, finding_id: UUID | None, today: date) -> Answer:
    with user_session(ctx) as session:
        return service.answer(session, ctx, question, today, finding_id)


def _visible(ctx: AccessContext, finding_id: UUID | None, today: date) -> UUID | None:
    """The finding the question was asked from, if this user may see it; another's is quietly dropped."""
    if finding_id is None:
        return None
    with user_session(ctx) as session:
        try:
            visible_finding(session, ctx, finding_id, today=today)
        except NotFoundError:
            return None
    return finding_id


def respond(
    gateway: Gateway | None,
    ctx: AccessContext,
    *,
    question: str,
    finding_id: UUID | None,
    thread_id: UUID | None,
    today: date,
) -> Iterator[Progress | Done]:
    if gateway is None:
        yield Done(_by_rules(ctx, question, finding_id, today), None)
        return
    finding_id = _visible(ctx, finding_id, today)
    past = history.replay(ctx, thread_id) if thread_id else []  # another person's thread → not found
    try:
        final: Final | None = None
        for event in converse(
            gateway, ctx, history=past, question=question, finding_id=finding_id, today=today
        ):
            if isinstance(event, Status):
                yield Progress(event.text)
            else:
                final = event
    except ModelUnavailableError:
        yield Done(_by_rules(ctx, question, finding_id, today), thread_id)
        return
    assert final is not None
    if final.verified:
        answer = Answer(
            final.text,
            source_finding_id=final.finding_ids[0] if final.finding_ids else None,
            source=CHECKED,
            suggestions=service.suggestions(ctx),
        )
    else:
        answer = _by_rules(ctx, question, finding_id, today)
        # The conversation keeps what the person saw, not the attempts that failed the check.
        final.new_messages.append({"role": "assistant", "content": [{"type": "text", "text": answer.text}]})
    if thread_id is None:
        thread_id = history.start(ctx, title=question, finding_id=finding_id)
    history.append(ctx, thread_id, final.new_messages, question=question, answer=answer.text)
    yield Done(answer, thread_id)
