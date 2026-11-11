"""The text of an agent's note by the model (stage 9, ADR 0010). The agents module knows no model: `writer`
gives it a `write` callable. Only the text is the model's — the title and the list stay the rules'; every
number of the text must be in the facts (strictly: counts are facts too). The model off, over the budget,
unreachable, or its text not passing: None, and the rules' text stays."""

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.service import Writer
from app.ai.gateway import BudgetError, Gateway, InvalidAnswerError, ModelUnavailableError
from app.ai.suggestions import ask
from app.ai.verify import unsupported
from app.tenancy.context import AccessContext

log = logging.getLogger(__name__)


class NoteText(BaseModel):
    text: str = Field(min_length=1, max_length=600, description="1–3 предложения для директора или УК")


def writer(gateway: Gateway, ctx: AccessContext) -> Writer:
    def write(agent: str, facts: dict[str, Any], rules_text: str) -> tuple[str, int] | None:
        basis = {"agent": agent, "facts": facts, "text_by_rules": rules_text}
        try:
            answer, chat = ask(
                gateway,
                ctx,
                task="agent",
                prompt_name="agent",
                basis=basis,
                answer=NoteText,
                check=lambda t: unsupported(t.text, [facts, rules_text], strict=True),
            )
        except (InvalidAnswerError, ModelUnavailableError, BudgetError) as exc:
            log.info("agent note by rules: %s", exc)
            return None
        return answer.text, chat.version

    return write
