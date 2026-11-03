"""The digest texts' eval (docs/08 part 1, stage 6): on the demo network the model writes the texts of every
latest digest — the network's and each restaurant's — and the code checks what a reader would notice:
- the model's text is used at all: every number from the digest's input, exactly its items (`digest_writer`);
  a text that fell back to the rules is a miss;
- «Главное за неделю» is 1–3 sentences;
- no engine jargon (module codes M1–M7) and no greeting;
- a restaurant's digest names no other restaurant — a leak fails the whole eval, whatever the score.

Target: ≥ 90 % of digests pass. Run with the real model: `uv run python -m app.ai.evals --suite digest`.
"""

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import digest_writer
from app.ai.gateway import Gateway
from app.digests.models import Digest
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant

TARGET = 0.9
JARGON = re.compile(r"\b[MМ][1-7]\b")  # Latin or Cyrillic «М»
GREETING = re.compile(r"\b(здравствуй|привет|добрый день|добрый вечер|доброе утро)", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?…]+(?:\s|$)")
ABBREVIATIONS = re.compile(
    r"\b(?:п\.\s?п|т\.\s?е|т\.\s?д|т\.\s?п|тыс|млн|млрд|руб|ед|шт|г|см)\.", re.IGNORECASE
)
GENERIC = {"ресторан", "ресторана", "на", "в", "у", "кафе", "точка", "бар"}


@dataclass
class Case:
    digest_id: UUID
    scope: str  # «сеть» or the restaurant's code
    data: dict[str, Any]
    others: list[str]  # other restaurants' codes and names: must not appear in a restaurant's digest


@dataclass
class Outcome:
    scope: str
    problems: list[str] = field(default_factory=list)
    leak: bool = False
    headline: str | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class Report:
    outcomes: list[Outcome]

    @property
    def score(self) -> float:
        return sum(o.ok for o in self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def passed(self) -> bool:
        return self.score >= TARGET and not any(o.leak for o in self.outcomes)

    def summary(self) -> str:
        good = sum(o.ok for o in self.outcomes)
        lines = [
            f"Сводки без замечаний: {good} из {len(self.outcomes)} ({self.score:.0%}), цель {TARGET:.0%}"
        ]
        if any(o.leak for o in self.outcomes):
            lines.append("  УТЕЧКА: в сводке ресторана названы другие рестораны")
        lines += [f"  ✗ {o.scope}: {'; '.join(o.problems)}" for o in self.outcomes if not o.ok]
        return "\n".join(lines)


def cases(owner: Session, tenant_id: UUID) -> list[Case]:
    """The latest digest of every scope of the network (read as the schema owner: an operator's tool)."""
    places = list(owner.execute(select(Restaurant).where(Restaurant.tenant_id == tenant_id)).scalars())
    latest = select(func.max(Digest.week_start)).where(Digest.tenant_id == tenant_id).scalar_subquery()
    rows = owner.execute(
        select(Digest).where(Digest.tenant_id == tenant_id, Digest.week_start == latest)
    ).scalars()
    out = []
    for d in rows:
        own = next((p for p in places if p.id == d.restaurant_id), None)
        others = [] if own is None else [x for p in places if p.id != own.id for x in (p.code, p.name)]
        out.append(Case(d.id, own.code if own else "сеть", d.input, others))
    return sorted(out, key=lambda c: c.scope)


def _stem(word: str) -> str:
    """The distinctive part of a Russian word, so «на Тверской» and «Тверская» match."""
    return word[: max(4, len(word) - 2)].lower()


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"\w+", name.lower()) if w not in GENERIC and len(w) > 3]


def _names(name: str, text: str, own: set[str] | None = None) -> bool:
    """`text` names the restaurant `name`: its code exactly, or a distinctive word of its name in any case
    and declension (code review 03.11.2026, p. 8). A word whose stem the digest's own restaurant shares
    («на Красном проспекте» and «на Красной») must appear as it is: the own name is no leak (TC-DG-40)."""
    if re.fullmatch(r"[A-Za-zА-Яа-я]{1,3}\d+", name):
        return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None
    said = re.findall(r"\w+", text.lower())
    stems = {_stem(w) for w in said if len(w) > 3}
    own = own or set()
    return any((w in said) if _stem(w) in own else (_stem(w) in stems) for w in _words(name))


def check(case: Case, written: dict[str, Any] | None) -> Outcome:
    o = Outcome(case.scope)
    if written is None:
        o.problems.append("текст модели не прошел проверку чисел или пунктов — сводка по правилам")
        return o
    headline = str(written["headline"])
    o.headline = headline
    texts = [headline, *(str(t) for t in written["items"].values())]
    sentences = len(SENTENCE_END.findall(ABBREVIATIONS.sub("", headline).strip() + " "))
    if not 1 <= sentences <= 3:
        o.problems.append(f"«Главное за неделю» — {sentences} предложений, нужно 1–3")
    if any(JARGON.search(t) for t in texts):
        o.problems.append("коды модулей движка в тексте")
    if any(GREETING.search(t) for t in texts):
        o.problems.append("приветствие")
    own_name = (case.data.get("restaurant") or {}).get("name") or ""
    own = {_stem(w) for w in _words(own_name)}
    named = sorted({x for x in case.others for t in texts if _names(x, t, own)})
    if named:
        o.leak = True
        o.problems.append(f"названы другие рестораны: {', '.join(named)}")
    return o


def run(gateway: Gateway, ctx: AccessContext, all_cases: list[Case]) -> Report:
    write = digest_writer.writer(gateway, ctx)
    outcomes = []
    for c in all_cases:
        result = write(c.data)  # measured, not kept: the stored digests stay as they are
        outcomes.append(check(c, result[0] if result else None))
    return Report(outcomes)
