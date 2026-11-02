"""The «почему так» eval (ADR 0008, stage 5.5): on the demo network every planted anomaly has a known cause
(`anomalies.json`, `cause`); the assistant's hypotheses for the finding the engine made of it must name that
cause among the top three in ≥ 80 % of cases. A proposal that failed the number check counts as a miss.

Run with the real model: `uv run python -m app.ai.evals --suite hypotheses`.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import Gateway, InvalidAnswerError
from app.ai.hypotheses import ask_for_finding
from app.insights.models import Finding
from app.tenancy.context import AccessContext

TARGET = 0.8


@dataclass
class Case:
    anomaly: str
    cause: str
    finding_id: UUID | None


@dataclass
class Outcome:
    anomaly: str
    cause: str
    proposed: list[str] = field(default_factory=list)
    problem: str | None = None

    @property
    def hit(self) -> bool:
        return self.cause in self.proposed[:3]


@dataclass
class Report:
    outcomes: list[Outcome]

    @property
    def score(self) -> float:
        return sum(o.hit for o in self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def passed(self) -> bool:
        return self.score >= TARGET

    def summary(self) -> str:
        hits = sum(o.hit for o in self.outcomes)
        lines = [f"Причина в топ-3: {hits} из {len(self.outcomes)} ({self.score:.0%}), цель {TARGET:.0%}"]
        lines += [
            f"  ✗ {o.anomaly}: ждали {o.cause}, предложено {o.proposed or '—'}"
            + (f" ({o.problem})" if o.problem else "")
            for o in self.outcomes
            if not o.hit
        ]
        return "\n".join(lines)


def matches(key: str, anomaly: dict[str, Any]) -> bool:
    """The engine's key of the finding made of a planted anomaly: module, restaurant (or network), item."""
    parts = key.split(":")
    if parts[:2] != [anomaly["module"], anomaly.get("restaurant") or "net"]:
        return False
    item = anomaly.get("menu_item") or anomaly.get("product")
    return item is None or item in "-".join(parts[2:]).split("-")


def cases(owner: Session, tenant_id: UUID, anomalies: list[dict[str, Any]]) -> list[Case]:
    rows = owner.execute(
        select(Finding.key, Finding.id).where(
            Finding.tenant_id == tenant_id, Finding.key.is_not(None), Finding.status != "dismissed"
        )
    ).all()
    keys = {key: fid for key, fid in rows}
    out = []
    for a in anomalies:
        found = [fid for key, fid in keys.items() if key and matches(key, a)]
        out.append(Case(a["id"], a["cause"], found[0] if found else None))
    return out


def run(gateway: Gateway, ctx: AccessContext, today: date, all_cases: list[Case]) -> Report:
    outcomes = []
    for c in all_cases:
        o = Outcome(c.anomaly, c.cause)
        if c.finding_id is None:
            o.problem = "движок не нашел находку"
        else:
            try:
                h = ask_for_finding(gateway, ctx, c.finding_id, today)  # measured, not kept
                o.proposed = [x.cause for x in h.hypotheses]
            except InvalidAnswerError as exc:
                o.problem = str(exc)
        outcomes.append(o)
    return Report(outcomes)
