"""A finding as this user may see it: the one read path for the screens, the chat and the assistant's tools.

Architecture review 27.10.2026, p. 10: a finding row that a director reads under row-level security still
holds other restaurants' figures — `evidence` (the engine's working numbers for the whole network) and, for
some findings, a table in `view` with every restaurant by name. Anything that shows a finding to a person or
hands it to the LLM goes through here, so what a director may see is decided once:

- `evidence` never leaves the server (the review's «Расчет по шагам» recomputes from the rows instead);
- the per-restaurant table of `view` goes only to those who may compare restaurants (`network.compare`);
- why a finding was rejected or reopened, and who reviewed it, is the HQ's working note (`findings.review`).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.insights import service
from app.insights.models import Finding, ReviewStatus
from app.insights.service import FindingWork
from app.insights.work import Work, WorkStage
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant, User
from app.tenancy.permissions import Permission


@dataclass(frozen=True)
class VisibleFinding:
    id: UUID
    restaurant_id: UUID | None
    restaurant_code: str | None
    restaurant_name: str | None
    kind: str
    process: str
    module: str | None
    confidence: str | None
    period_from: date | None
    period_to: date | None
    review_status: str | None
    review_reason: str | None
    review_note: str | None
    reviewed_on: date | None
    reviewed_by_name: str | None
    title: str
    headline: str | None
    effect_rub_month: Decimal | None
    effect_note: str | None
    actions: list[str]
    status: str
    found_on: date
    work: Work
    view: dict[str, Any] | None


def view_for(view: dict[str, Any] | None, ctx: AccessContext) -> dict[str, Any] | None:
    """A director sees their own figures and the network's average, never other restaurants by name."""
    if not view or not view.get("table_names_restaurants"):
        return view
    if ctx.can(Permission.NETWORK_COMPARE):
        return view
    return {k: v for k, v in view.items() if k not in ("table", "table_names_restaurants")}


def _reviewer_names(session: Session, findings: list[Finding]) -> dict[UUID | None, str]:
    """Names of the people who reviewed these findings (row-level security hides them from a director)."""
    ids = {f.reviewed_by for f in findings if f.reviewed_by}
    if not ids:
        return {}
    return dict(session.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def visible(session: Session, ctx: AccessContext, items: list[FindingWork]) -> list[VisibleFinding]:
    hq = ctx.can(Permission.FINDINGS_REVIEW)
    reviewers = _reviewer_names(session, [fw.finding for fw in items]) if hq else {}
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}  # what the caller may see
    out = []
    for fw in items:
        f = fw.finding
        place = places.get(f.restaurant_id) if f.restaurant_id else None
        out.append(
            VisibleFinding(
                id=f.id,
                restaurant_id=f.restaurant_id,
                restaurant_code=place.code if place else None,
                restaurant_name=place.name if place else None,
                kind=f.kind,
                process=f.process,
                module=f.module,
                confidence=f.confidence,
                period_from=f.period_from,
                period_to=f.period_to,
                review_status=f.review_status,
                review_reason=f.review_reason if hq else None,
                review_note=f.review_note if hq else None,
                reviewed_on=f.reviewed_on,
                reviewed_by_name=reviewers.get(f.reviewed_by),
                title=f.title,
                headline=f.headline,
                effect_rub_month=f.effect_rub_month,
                effect_note=f.effect_note,
                actions=list(f.actions),
                status=f.status,
                found_on=f.found_on,
                work=fw.work,
                view=view_for(f.view, ctx),
            )
        )
    return out


def visible_finding(session: Session, ctx: AccessContext, finding_id: UUID, *, today: date) -> VisibleFinding:
    """One finding by the card's rules: missing or not visible to the caller → NotFoundError."""
    (one,) = visible(session, ctx, [service.get_finding(session, finding_id, today=today)])
    return one


def visible_findings(
    session: Session,
    ctx: AccessContext,
    *,
    today: date,
    stage: WorkStage | None = None,
    restaurant_id: UUID | None = None,
    late_only: bool = False,
    review: ReviewStatus | None = None,
) -> list[VisibleFinding]:
    items = service.list_findings(
        session, today=today, stage=stage, restaurant_id=restaurant_id, late_only=late_only, review=review
    )
    return visible(session, ctx, items)
