"""The analyst's pre-check of a finding before the manual review (ADR 0008, stage 5.5).

Two parts, and only the second is the model's:
- **what to look at** — computed by the code, with or without the model: problems with the data of the same
  restaurant, a one-off spike, a change of supplier, public holidays in the period, too few data, a failed
  check of the step-by-step verification;
- **a draft verdict** — the model reads the facts and those flags and proposes «подтвердить»,
  «отклонить» (with a reason, as the review form asks) or «посмотреть внимательнее», with its reasoning.
  The analyst decides; how often the draft matched the decision is the material for tuning (`stats`).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import finding_context
from app.ai.gateway import Gateway
from app.ai.models import AiSuggestion
from app.ai.suggestions import Proposal, propose
from app.analytics.verify import verify
from app.catalog.models import Product
from app.core.errors import ForbiddenError
from app.insights.models import Finding
from app.insights.visible import visible_finding
from app.operations.models import Receipt, WriteOff
from app.tenancy.context import AccessContext, user_session
from app.tenancy.permissions import Permission

# Public holidays of the Russian calendar (month, day): demand and write-offs differ on them.
HOLIDAYS = {(1, d) for d in range(1, 9)} | {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4), (12, 31)}
SPIKE_SHARE = Decimal("0.5")  # one day holds half of the period's write-offs or purchases of the product
FEW_DAYS = 14


@dataclass(frozen=True)
class Flag:
    code: str
    title: str
    note: str


def _spike(
    session: Session, model: Any, product_id: UUID, restaurant_id: UUID, start: date, end: date
) -> date | None:
    by_day = session.execute(
        select(model.day, func.sum(model.qty))
        .where(
            model.product_id == product_id,
            model.restaurant_id == restaurant_id,
            model.day.between(start, end),
        )
        .group_by(model.day)
    ).all()
    total = sum((q for _, q in by_day), Decimal(0))
    if not total or len(by_day) < 3:
        return None
    top_day, top = max(by_day, key=lambda r: r[1])
    return top_day if top / total >= SPIKE_SHARE else None


def flags(session: Session, finding: Finding, today: date) -> list[Flag]:
    """What the analyst should look at before confirming — facts, not opinions (code review 02.11.2026,
    p. 12: only what can explain this finding, so the list does not cry wolf)."""
    out: list[Flag] = []
    end = finding.period_to or today
    start = min(finding.period_from or end - timedelta(days=28), end)
    if finding.restaurant_id is not None:
        problems = (
            session.execute(
                select(Finding.title).where(
                    Finding.restaurant_id == finding.restaurant_id,
                    Finding.module == "M7",
                    Finding.status != "dismissed",
                    Finding.review_status.is_distinct_from(
                        "rejected"
                    ),  # rejected as false: not a data problem
                    Finding.id != finding.id,
                )
            )
            .scalars()
            .all()
        )
        if problems:
            out.append(Flag("data_problems", "Проблемы с данными ресторана", "; ".join(problems)))
    spike_days: list[date] = []
    product_code, _ = finding_context.subject_of_key(finding.module, finding.key)
    product = (
        session.execute(select(Product).where(Product.code == product_code)).scalar()
        if product_code
        else None
    )
    if product is not None and finding.restaurant_id is not None:
        for model, what in ((WriteOff, "списаний"), (Receipt, "закупок")):
            day = _spike(session, model, product.id, finding.restaurant_id, start, end)
            if day:
                spike_days.append(day)
                out.append(
                    Flag(
                        "one_off",
                        "Разовый всплеск",
                        f"Больше половины {what} товара за период — {day:%d.%m.%Y}",
                    )
                )

        # A change of supplier: one appears in the period that did not sell the product in the 60 days before.
        def suppliers(a: date, b: date) -> set[UUID | None]:
            return set(
                session.execute(
                    select(Receipt.supplier_id)
                    .distinct()
                    .where(
                        Receipt.product_id == product.id,
                        Receipt.restaurant_id == finding.restaurant_id,
                        Receipt.supplier_id.is_not(None),
                        Receipt.day.between(a, b),
                    )
                ).scalars()
            )

        before = suppliers(start - timedelta(days=60), start - timedelta(days=1))
        if before and suppliers(start, end) - before:
            out.append(
                Flag(
                    "supplier_change",
                    "Сменился поставщик",
                    "В периоде появился поставщик, у которого товар раньше не брали",
                )
            )
    # Holidays explain a deviation only on the day it happened, or in a short period.
    days = (end - start).days + 1
    holidays = sorted(
        {d for d in (start + timedelta(n) for n in range(days)) if (d.month, d.day) in HOLIDAYS}
    )
    near = [d for d in holidays if any(abs((d - s).days) <= 1 for s in spike_days)] or (
        holidays if days <= 31 else []
    )
    if near:
        out.append(Flag("holidays", "Праздники в периоде", ", ".join(f"{d:%d.%m}" for d in near)))
    if days < FEW_DAYS:
        out.append(Flag("few_data", "Мало данных", f"Период — {days} дн."))
    failed = [c["check"] for c in verify(session, finding).get("checks") or [] if not c.get("ok")]
    if failed:
        out.append(Flag("verification", "Сверка с данными не прошла", "; ".join(failed)))
    return out


class Draft(BaseModel):
    verdict: Literal["confirm", "reject", "look_closer"]
    reason: Literal["data", "logic", "false_alarm", "other"] | None = Field(
        description="Только для «reject»: данные неверны, правило неверно, не проблема, другое"
    )
    rationale: str = Field(description="Почему такой вердикт — по фактам и флагам")
    look_at: list[str] = Field(description="Что аналитику посмотреть в первую очередь")


def _reason_only_with_reject(d: Draft) -> list[str]:
    if (d.verdict == "reject") != (d.reason is not None):
        return ["причина нужна только при «reject» и обязательна для него"]
    return []


def _may_review(ctx: AccessContext) -> None:
    if not ctx.can(Permission.FINDINGS_REVIEW):
        raise ForbiddenError("Предпроверка — для тех, кто проверяет находки")


def look_at(ctx: AccessContext, finding_id: UUID, today: date) -> list[Flag]:
    _may_review(ctx)
    with user_session(ctx) as session:
        visible_finding(session, ctx, finding_id, today=today)
        finding = session.get(Finding, finding_id)
        assert finding is not None
        return flags(session, finding, today)


def propose_draft(gateway: Gateway, ctx: AccessContext, finding_id: UUID, today: date) -> Proposal:
    _may_review(ctx)
    with user_session(ctx) as session:
        basis = finding_context.build(session, ctx, finding_id, today)
        finding = session.get(Finding, finding_id)
        assert finding is not None
        basis["flags"] = [f.__dict__ for f in flags(session, finding, today)]
        # Whether the finding still waited for its verdict: only such a draft can be compared with it.
        basis["review_status_when_drafted"] = finding.review_status
        restaurant_id = finding.restaurant_id
    return propose(
        gateway,
        ctx,
        kind="precheck",
        task="precheck",
        prompt_name="precheck",
        basis=basis,
        answer=Draft,
        subject_id=finding_id,
        restaurant_id=restaurant_id,
        check=_reason_only_with_reject,
    )


@dataclass(frozen=True)
class Stats:
    drafts: int
    decided: int
    agreed: int


def stats(ctx: AccessContext) -> Stats:
    """«ИИ предлагал / человек решил»: per finding, the last draft made while it waited for review, against
    the verdict (code review 02.11.2026, p. 13: one draft per finding; one after the verdict counts not)."""
    _may_review(ctx)
    match = {"confirm": "confirmed", "reject": "rejected"}
    with user_session(ctx) as session:
        rows = session.execute(
            select(AiSuggestion.subject_id, AiSuggestion.content, AiSuggestion.basis, Finding.review_status)
            .join(Finding, Finding.id == AiSuggestion.subject_id)
            .where(AiSuggestion.kind == "precheck")
            .order_by(AiSuggestion.created_at)
        ).all()
    last: dict[UUID, tuple[dict[str, Any], str | None]] = {}
    for subject, content, basis, status in rows:
        if basis.get("review_status_when_drafted") != "pending":
            continue  # made after the verdict
        last[subject] = (content, status if status in ("confirmed", "rejected") else None)
    verdicts = [(c, s) for c, s in last.values() if s is not None]
    agreed = sum(1 for c, s in verdicts if match.get(c["verdict"]) == s)
    return Stats(len(last), len(verdicts), agreed)
