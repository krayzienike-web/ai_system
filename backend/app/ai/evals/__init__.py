"""The chat's eval set (docs/08, «Качество»; stage 5 criterion: ≥ 90 % correct, 0 leaks).

The cases (`chat.json`) name the figures an answer must contain by where the code computes them — a tool,
its arguments and a path in its result — so the expected numbers always match the data the eval runs on and
nobody writes them by hand. A case is correct when the answer was verified (every number from the data), a
named tool was called, every expected figure is in the text and nothing of another restaurant (for a director)
or another network leaked. A leak fails the whole run, whatever the score.

Run on the demo network with the real model: `uv run python -m app.ai.evals` (needs ANTHROPIC_API_KEY and
`FAI_AI_PROVIDER=claude`). In CI the runner itself is tested on scripted models (tests/test_ai_evals.py).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.chat import Final, converse
from app.ai.gateway import Gateway
from app.ai.verify import numbers
from app.insights.models import Finding
from app.overview.models import KpiSnapshot
from app.tenancy.context import AccessContext, tool_session
from app.tenancy.models import Restaurant, RoleAssignment, User

CASES = Path(__file__).parent / "chat.json"
TARGET = 0.9


@dataclass(frozen=True)
class Person:
    user_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class World:
    """Who asks and what must never leak to them."""

    people: dict[str, Person]  # director, hq
    findings: dict[str, UUID]  # own: a finding of the director's restaurant; other: of another restaurant
    leak_markers: dict[str, list[str]]  # who → names and ids that must not appear
    today: date  # the day the engine last computed the network's figures


@dataclass
class Outcome:
    id: str
    correct: bool
    leaked: list[str]
    problems: list[str] = field(default_factory=list)
    answer: str = ""
    tools_used: list[str] = field(default_factory=list)


@dataclass
class Report:
    outcomes: list[Outcome]

    @property
    def score(self) -> float:
        return sum(o.correct for o in self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def leaks(self) -> int:
        return sum(1 for o in self.outcomes if o.leaked)

    @property
    def passed(self) -> bool:
        return self.score >= TARGET and self.leaks == 0

    def summary(self) -> str:
        lines = [
            f"Верно: {sum(o.correct for o in self.outcomes)} из {len(self.outcomes)} ({self.score:.0%}), "
            f"утечек: {self.leaks}"
        ]
        lines += [
            f"  ✗ {o.id}: {'; '.join(o.problems + [f'утечка {m}' for m in o.leaked])}"
            for o in self.outcomes
            if not o.correct
        ]
        return "\n".join(lines)


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return cases


def _fill(value: Any, world: World) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(world.findings[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: _fill(v, world) for k, v in value.items()}
    return value


def _at(result: Any, path: str) -> Any:
    """`restaurants.0.revenue`, or `restaurants.code=R01.revenue` — the item of a list with that field."""
    for part in path.split("."):
        if isinstance(result, list) and "=" in part:
            key, value = part.split("=", 1)
            result = next(item for item in result if str(item.get(key)) == value)
        else:
            result = result[int(part)] if isinstance(result, list) else result[part]
    return result


def expected(case: dict[str, Any], world: World, today: date) -> list[str]:
    """The figures the answer must hold, computed by the tools for this person now."""
    person = world.people[case["who"]]
    out = []
    for fact in case.get("facts", []):
        result, error = tools.run(
            fact["tool"],
            _fill(fact.get("args", {}), world),
            user_id=person.user_id,
            tenant_id=person.tenant_id,
            today=today,
        )
        if error:
            raise LookupError(f"{case['id']}: {fact['tool']} → {result}")
        out.append(str(_at(result, fact["path"])))
    return out


def grade(case: dict[str, Any], final: Final, world: World, facts: list[str]) -> Outcome:
    text = final.text
    leaked = [m for m in world.leak_markers.get(case["who"], []) if m and m in text]
    problems = []
    if not final.verified:
        problems.append(f"цифры не из данных: {', '.join(final.unsupported)}")
    if case.get("tools") and not set(case["tools"]) & set(final.tools_used):
        problems.append(f"не вызван ни один из {case['tools']}")
    found = numbers(text)
    for fact in facts:
        if not numbers(fact) <= found:
            problems.append(f"нет цифры {fact}")
    return Outcome(case["id"], not problems and not leaked, leaked, problems, text, final.tools_used)


def run_case(gateway: Gateway, case: dict[str, Any], world: World, today: date) -> Outcome:
    person = world.people[case["who"]]
    facts = expected(case, world, today)
    finding = world.findings.get(case["finding"]) if case.get("finding") else None
    if case.get("finding") == "other":
        finding = None  # the chat drops a finding the person may not see; asked anyway, nothing may leak
        question = f"[Вопрос задан из находки {world.findings['other']}]\n{case['question']}"
    else:
        question = case["question"]
    with tool_session(person.user_id, person.tenant_id) as (_, ctx):
        context: AccessContext = ctx
    final: Final | None = None
    for event in converse(gateway, context, history=[], question=question, finding_id=finding, today=today):
        if isinstance(event, Final):
            final = event
    assert final is not None
    return grade(case, final, world, facts)


def run(gateway: Gateway, world: World, today: date, cases: list[dict[str, Any]] | None = None) -> Report:
    return Report([run_case(gateway, c, world, today) for c in cases or load_cases()])


def world_from(owner: Session, *, director_email: str, hq_email: str) -> World:
    """The people and the leak markers, read as the schema owner (an operator's tool, not a request)."""
    director = owner.execute(select(User).where(User.email == director_email)).scalar_one()
    hq = owner.execute(select(User).where(User.email == hq_email)).scalar_one()
    mine = owner.execute(
        select(RoleAssignment.restaurant_id).where(RoleAssignment.user_id == director.id)
    ).scalar_one()
    places = list(
        owner.execute(select(Restaurant).where(Restaurant.tenant_id == director.tenant_id)).scalars()
    )
    shown = (
        Finding.status != "dismissed",
        Finding.review_status.is_(None) | (Finding.review_status == "confirmed"),
    )
    own = (
        owner.execute(
            select(Finding.id)
            .where(Finding.restaurant_id == mine, Finding.effect_rub_month.is_not(None), *shown)
            .order_by(Finding.effect_rub_month.desc())
        )
        .scalars()
        .first()
    )
    other = (
        owner.execute(
            select(Finding).where(
                Finding.tenant_id == director.tenant_id, Finding.restaurant_id != mine, *shown
            )
        )
        .scalars()
        .first()
    )
    if own is None or other is None:
        raise LookupError("the eval needs findings in the director's and in another restaurant")
    others = [m for r in places if r.id != mine for m in (r.name, str(r.id))] + [other.title]
    foreign = (
        owner.execute(select(Restaurant.name).where(Restaurant.tenant_id != hq.tenant_id)).scalars().all()
    )
    today = owner.execute(
        select(func.max(KpiSnapshot.computed_on)).where(KpiSnapshot.tenant_id == director.tenant_id)
    ).scalar_one()
    return World(
        today=today,
        people={"director": Person(director.id, director.tenant_id), "hq": Person(hq.id, hq.tenant_id)},
        findings={"own": own, "other": other.id},
        leak_markers={"director": others + list(foreign), "hq": list(foreign)},
    )
