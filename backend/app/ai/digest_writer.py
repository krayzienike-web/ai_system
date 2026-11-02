"""The digest's texts by the model (docs/08 part 1, stage 6): «Главное за неделю» and a text per item.

The digests module knows no model: `writer` gives it a `write` callable. The model writes by a schema, every
number is checked against the digest's input (one request to correct, `suggestions.ask`), and the items must
be exactly the digest's. When the model is off, over the budget, unreachable or its text does not pass,
`write` answers None and the digest is written by rules (`app/digests/texts.py`).
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.ai.gateway import BudgetError, Gateway, InvalidAnswerError, ModelUnavailableError
from app.ai.suggestions import ask
from app.digests.service import Writer
from app.digests.texts import by_rules
from app.tenancy.context import AccessContext

log = logging.getLogger(__name__)


class ItemText(BaseModel):
    finding_id: str
    text: str = Field(description="1–2 предложения: что видно, сколько стоит, первый шаг")


class Texts(BaseModel):
    headline: str = Field(description="Главное за неделю: 2–3 предложения")
    items: list[ItemText]


def _ids(data: dict[str, Any]) -> list[str]:
    return [i["finding_id"] for i in data["problems"] + data["opportunities"] + data["risks"]]


def writer(gateway: Gateway, ctx: AccessContext) -> Writer:
    def write(data: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
        expected = _ids(data)

        def same_items(t: Texts) -> list[str]:
            got = [i.finding_id for i in t.items]
            if sorted(got) != sorted(expected):
                return ["тексты нужны ровно для пунктов сводки, по одному на каждый finding_id из фактов"]
            return []

        try:
            texts, chat = ask(
                gateway,
                ctx,
                task="digest",
                prompt_name="digest",
                basis=data,
                answer=Texts,
                check=same_items,
                facts_of=lambda t: [t.headline, *(i.text for i in t.items)],
            )
        except (InvalidAnswerError, ModelUnavailableError, BudgetError) as exc:
            log.info("digest by rules: %s", exc)
            return None
        rules = by_rules(data)
        items = {i.finding_id: i.text for i in texts.items}
        return {
            "headline": texts.headline,
            "items": {k: items.get(k, v) for k, v in rules["items"].items()},
        }, (chat.version)

    return write
