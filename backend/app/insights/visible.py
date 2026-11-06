"""A finding as this user may see it: the one read path for the screens, the chat and the assistant's tools.

Architecture review 27.10.2026, p. 10: a finding row that a director reads under row-level security still
holds other restaurants' figures — `evidence` (the engine's working numbers for the whole network) and, for
some findings, a table in `view` with every restaurant by name. Anything that shows a finding to a person or
hands it to the LLM goes through here, so what a director may see is decided once:

- `evidence` never leaves the server (the review's «Расчет по шагам» recomputes from the rows instead);
- the per-restaurant table of `view` goes only to those who may compare restaurants (`network.compare`);
- why a finding was rejected or reopened, and who reviewed it, is the HQ's working note (`findings.review`);
- a linked finding's story (docs/12) lists only the other findings of it that this user may see.
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
class StoryMember:
    id: UUID
    title: str
    module: str | None
    kind: str
    effect_rub_month: Decimal | None
    restaurant_code: str | None


@dataclass(frozen=True)
class Story:
    """Findings of one cause (docs/12, «Связанные находки»): one sum — the largest one's, not their total."""

    key: str
    title: str
    effect_rub_month: Decimal | None
    findings: list[StoryMember]  # the others, as this user may see them


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
    story: Story | None = None


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


def _stories(
    session: Session, ctx: AccessContext, findings: list[Finding], places: dict[UUID, Restaurant]
) -> dict[str, list[Finding]]:
    """The findings of these findings' stories that the caller may see (row-level security reads them)."""
    keys = {f.story_key for f in findings if f.story_key}
    if not keys:
        return {}
    out: dict[str, list[Finding]] = {}
    for f in session.execute(
        select(Finding).where(
            Finding.tenant_id == ctx.tenant_id,
            Finding.story_key.in_(keys),
            Finding.status != "dismissed",
            Finding.review_status.is_distinct_from(ReviewStatus.REJECTED),
        )
    ).scalars():
        if f.restaurant_id is None or f.restaurant_id in places:
            out.setdefault(f.story_key or "", []).append(f)
    return out


def _story(f: Finding, stories: dict[str, list[Finding]], places: dict[UUID, Restaurant]) -> Story | None:
    members = stories.get(f.story_key or "", [])
    others = [m for m in members if m.id != f.id]
    if not f.story_key or not others:
        return None
    effects = [m.effect_rub_month for m in members if m.effect_rub_month is not None]
    return Story(
        key=f.story_key,
        title=f.story_title or f.title,
        effect_rub_month=max(effects) if effects else None,
        findings=[
            StoryMember(
                id=m.id,
                title=m.title,
                module=m.module,
                kind=m.kind,
                effect_rub_month=m.effect_rub_month,
                restaurant_code=places[m.restaurant_id].code if m.restaurant_id in places else None,
            )
            for m in sorted(others, key=lambda m: (m.module or "", m.title))
        ],
    )


def visible(session: Session, ctx: AccessContext, items: list[FindingWork]) -> list[VisibleFinding]:
    hq = ctx.can(Permission.FINDINGS_REVIEW)
    reviewers = _reviewer_names(session, [fw.finding for fw in items]) if hq else {}
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}  # what the caller may see
    stories = _stories(session, ctx, [fw.finding for fw in items], places)
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
                story=_story(f, stories, places),
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
