"""The assistant's proposals and people's decisions on them (ADR 0008; `ai_suggestions`).

A proposal is made in steps that never hold the request's transaction (the model may think for a minute):
the code gathers the facts → the model proposes by a schema → every number of the proposal is checked
against the facts (one request to correct, then no proposal) → it is kept as `proposed`, and the previous
proposal on the same subject becomes `superseded`. Only a person accepts or rejects it.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai import prompt as prompts
from app.ai.gateway import Gateway, InvalidAnswerError, Task
from app.ai.models import AiSuggestion
from app.ai.prompt import Prompt
from app.ai.verify import unsupported
from app.core.errors import ForbiddenError, NotFoundError
from app.insights.visible import visible_finding
from app.tenancy.context import AccessContext, user_session
from app.tenancy.permissions import Permission

# Who may decide on a proposal of each kind: hypotheses — anyone who sees them (a director takes one up or
# not); the others change the HQ's work.
DECIDE: dict[str, Permission | None] = {
    "hypotheses": None,
    "precheck": Permission.FINDINGS_REVIEW,
    "finding_idea": Permission.FINDINGS_REVIEW,
    "mapping": Permission.DATA_UPLOAD,
}
FINDING_KINDS = ("hypotheses", "precheck")  # proposals about a finding follow the finding's visibility
CORRECT = (
    "Проверка: числа {numbers} не найдены в фактах. Исправь предложение: используй только числа из фактов, "
    "ничего не считай сам."
)


@dataclass(frozen=True)
class Proposal:
    id: UUID
    kind: str
    subject_id: UUID | None
    content: dict[str, Any]
    basis: dict[str, Any]
    status: str
    prompt_version: int
    created_at: datetime


def _texts(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def ask[P: BaseModel](
    gateway: Gateway,
    ctx: AccessContext,
    *,
    task: Task,
    prompt_name: str,
    basis: dict[str, Any],
    answer: type[P],
    check: Callable[[P], list[str]] | None = None,
) -> tuple[P, Prompt]:
    """Ask the model by the schema of `answer`; every number must be in `basis`, and `check` (the kind's own
    rules) must pass. One request to correct, then `InvalidAnswerError`: no proposal."""
    chat = prompts.load(prompt_name)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": f"Факты (посчитаны кодом):\n{_texts(basis)}"}]}
    ]
    for attempt in range(2):
        result = gateway.structured(ctx, task=task, prompt=chat, messages=messages, answer=answer)
        problems = unsupported(_texts(result.model_dump(mode="json")), [basis])
        if check is not None:
            problems += check(result)
        if not problems:
            return result, chat
        if attempt == 1:
            break
        messages += [
            {"role": "assistant", "content": [{"type": "text", "text": result.model_dump_json()}]},
            {
                "role": "user",
                "content": [{"type": "text", "text": CORRECT.format(numbers=", ".join(problems))}],
            },
        ]
    raise InvalidAnswerError(f"the proposal does not match the facts: {', '.join(problems)}")


def keep(
    ctx: AccessContext,
    *,
    kind: str,
    subject_id: UUID | None,
    restaurant_id: UUID | None,
    contents: list[dict[str, Any]],
    basis: dict[str, Any],
    chat: Prompt,
) -> list[Proposal]:
    """Store proposals; those still undecided on the same subject become `superseded`."""
    with user_session(ctx) as s:
        s.execute(
            update(AiSuggestion)
            .where(
                AiSuggestion.kind == kind,
                AiSuggestion.subject_id == subject_id,
                AiSuggestion.status == "proposed",
            )
            .values(status="superseded")
        )
        rows = [
            AiSuggestion(
                tenant_id=ctx.tenant_id,
                kind=kind,
                subject_id=subject_id,
                restaurant_id=restaurant_id,
                content=content,
                basis=basis,
                prompt=chat.name,
                prompt_version=chat.version,
                status="proposed",
                created_by=ctx.user_id,
            )
            for content in contents
        ]
        s.add_all(rows)
        s.flush()
        return [out(r) for r in rows]


def propose[P: BaseModel](
    gateway: Gateway,
    ctx: AccessContext,
    *,
    kind: str,
    task: Task,
    prompt_name: str,
    basis: dict[str, Any],
    answer: type[P],
    subject_id: UUID | None,
    restaurant_id: UUID | None,
    check: Callable[[P], list[str]] | None = None,
) -> Proposal:
    """One proposal on a subject: asked, checked, kept."""
    result, chat = ask(
        gateway, ctx, task=task, prompt_name=prompt_name, basis=basis, answer=answer, check=check
    )
    (kept,) = keep(
        ctx,
        kind=kind,
        subject_id=subject_id,
        restaurant_id=restaurant_id,
        contents=[result.model_dump(mode="json")],
        basis=basis,
        chat=chat,
    )
    return kept


def out(row: AiSuggestion) -> Proposal:
    return Proposal(
        row.id,
        row.kind,
        row.subject_id,
        row.content,
        row.basis,
        row.status,
        row.prompt_version,
        row.created_at,
    )


def latest(ctx: AccessContext, kind: str, subject_id: UUID | None) -> Proposal | None:
    """The current proposal on the subject that the caller may see (decided ones too), or none."""
    with user_session(ctx) as s:
        row = (
            s.execute(
                select(AiSuggestion)
                .where(
                    AiSuggestion.kind == kind,
                    AiSuggestion.subject_id == subject_id,
                    AiSuggestion.status != "superseded",
                )
                .order_by(AiSuggestion.created_at.desc())
            )
            .scalars()
            .first()
        )
        return out(row) if row else None


@contextmanager
def deciding(
    ctx: AccessContext, suggestion_id: UUID, *, today: date
) -> Iterator[tuple[Session, AiSuggestion]]:
    """A proposal locked for a decision, if the caller may see it and decide on it."""
    with user_session(ctx) as s:
        row = s.get(AiSuggestion, suggestion_id, with_for_update=True)  # another restaurant's: not visible
        if row is None or row.status == "superseded":
            raise NotFoundError("Предложение не найдено")
        if row.kind in FINDING_KINDS and row.subject_id is not None:
            visible_finding(
                s, ctx, row.subject_id, today=today
            )  # the card's rules: one under review is hidden
        needed = DECIDE[row.kind]
        if needed is not None and not ctx.can(needed):
            raise ForbiddenError("Решение по этому предложению принимает управляющая компания")
        yield s, row
        row.decided_by, row.decided_at = ctx.user_id, datetime.now(UTC)
        s.flush()


def decide(
    ctx: AccessContext, suggestion_id: UUID, *, accepted: bool, note: str | None, today: date
) -> Proposal:
    with deciding(ctx, suggestion_id, today=today) as (_, row):
        row.status = "accepted" if accepted else "rejected"
        row.decision_note = note
    return out(row)
