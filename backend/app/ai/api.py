"""The assistant's proposals on the screens (ADR 0008): «Почему так» on a finding, decisions on proposals."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import digest_writer, discover, hypotheses, mapping, precheck, suggestions
from app.ai.gateway import Gateway, ModelUnavailableError, get_gateway
from app.ai.suggestions import Proposal
from app.core.deps import SessionDep, require
from app.core.errors import NotFoundError
from app.core.period import TodayDep
from app.digests import api as digests_api
from app.digests import builder as digest_builder
from app.digests import service as digest_service
from app.digests.models import Digest
from app.imports.templates import TEMPLATES
from app.insights.visible import visible_finding
from app.tenancy.context import AccessContext, user_session
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

router = APIRouter(tags=["assistant"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]
CanAsk = Annotated[AccessContext, Depends(require(Permission.AI_CHAT))]
CanReview = Annotated[AccessContext, Depends(require(Permission.FINDINGS_REVIEW))]
GatewayDep = Annotated[Gateway | None, Depends(get_gateway)]


class HypothesisOut(BaseModel):
    cause: str
    cause_title: str
    likelihood: str
    why: str
    check: str


class HypothesesOut(BaseModel):
    id: UUID
    status: str
    created_at: datetime
    hypotheses: list[HypothesisOut]
    steps: list[str]
    rules_note: str | None
    basis: dict[str, Any]  # what it was made from
    basis_words: list[
        str
    ]  # the same in words, for «Почему я это вижу» (ADR 0007: the screen computes nothing)
    decided_by_me: (
        bool  # a decision is shared: the screen says whose it is (code review 02.11.2026, front p. 3)
    )

    @classmethod
    def of(cls, p: Proposal, ctx: AccessContext) -> "HypothesesOut":
        c = p.content
        return cls(
            id=p.id,
            status=p.status,
            created_at=p.created_at,
            basis_words=hypotheses.basis_words(p.basis),
            decided_by_me=p.decided_by == ctx.user_id,
            hypotheses=[
                HypothesisOut(**h, cause_title=hypotheses.CAUSES.get(h["cause"], h["cause"]))
                for h in c["hypotheses"]
            ],
            steps=c["steps"],
            rules_note=c.get("rules_note"),
            basis={k: v for k, v in p.basis.items() if k != "causes_to_choose_from"},
        )


class DecisionIn(BaseModel):
    accepted: bool
    note: str | None = None


class DecisionOut(BaseModel):
    id: UUID
    status: str


def _visible(ctx: AccessContext, finding_id: UUID, today: Any) -> None:
    """The card's rules first: no proposal about a finding the caller may not see (one under review, say)."""
    with user_session(ctx) as session:
        visible_finding(session, ctx, finding_id, today=today)


@router.get("/findings/{finding_id}/hypotheses")
def get_hypotheses(finding_id: UUID, ctx: CanRead, today: TodayDep) -> HypothesesOut | None:
    _visible(ctx, finding_id, today)
    p = suggestions.latest(ctx, "hypotheses", finding_id)
    return HypothesesOut.of(p, ctx) if p else None


@router.post("/findings/{finding_id}/hypotheses")
def make_hypotheses(
    finding_id: UUID, ctx: CanAsk, session: SessionDep, gateway: GatewayDep, today: TodayDep
) -> HypothesesOut:
    _release(session)
    _visible(ctx, finding_id, today)  # access first: another's finding is «not found», model or not
    if gateway is None:
        raise ModelUnavailableError("Ассистент пока не подключен")
    return HypothesesOut.of(hypotheses.propose_for_finding(gateway, ctx, finding_id, today), ctx)


@router.post("/ai/suggestions/{suggestion_id}/decision")
def decide(suggestion_id: UUID, body: DecisionIn, ctx: CanRead, today: TodayDep) -> DecisionOut:
    p = suggestions.decide(ctx, suggestion_id, accepted=body.accepted, note=body.note, today=today)
    return DecisionOut(id=p.id, status=p.status)


class FlagOut(BaseModel):
    code: str
    title: str
    note: str


class PrecheckDraftOut(BaseModel):
    id: UUID
    status: str
    created_at: datetime
    verdict: str
    reason: str | None
    rationale: str
    look_at: list[str]


class PrecheckOut(BaseModel):
    flags: list[FlagOut]  # computed by the code: shown with or without the model
    draft: PrecheckDraftOut | None  # the model's draft verdict, if asked


class PrecheckStatsOut(BaseModel):
    drafts: int
    decided: int
    agreed: int


def _draft(p: Proposal | None) -> PrecheckDraftOut | None:
    return PrecheckDraftOut(id=p.id, status=p.status, created_at=p.created_at, **p.content) if p else None


@router.get("/findings/{finding_id}/precheck")
def get_precheck(finding_id: UUID, ctx: CanReview, today: TodayDep) -> PrecheckOut:
    flags = precheck.look_at(ctx, finding_id, today)
    return PrecheckOut(
        flags=[FlagOut(**f.__dict__) for f in flags],
        draft=_draft(suggestions.latest(ctx, "precheck", finding_id)),
    )


@router.post("/findings/{finding_id}/precheck")
def make_precheck(
    finding_id: UUID, ctx: CanReview, session: SessionDep, gateway: GatewayDep, today: TodayDep
) -> PrecheckOut:
    _release(session)
    flags = precheck.look_at(ctx, finding_id, today)  # access first, model or not
    if gateway is None:
        raise ModelUnavailableError("Ассистент пока не подключен")
    draft = precheck.propose_draft(gateway, ctx, finding_id, today)
    return PrecheckOut(flags=[FlagOut(**f.__dict__) for f in flags], draft=_draft(draft))


@router.get("/ai/precheck/stats")
def precheck_stats(ctx: CanReview) -> PrecheckStatsOut:
    """«ИИ предлагал / человек решил»: how often the draft matched the analyst's verdict."""
    s = precheck.stats(ctx)
    return PrecheckStatsOut(drafts=s.drafts, decided=s.decided, agreed=s.agreed)


class IdeaOut(BaseModel):
    id: UUID
    status: str
    created_at: datetime
    title: str
    pattern: str
    why_it_matters: str
    rule_sketch: str
    evidence: list[dict[str, Any]]  # the aggregate rows the idea rests on, as the code computed them
    evidence_text: list[str]  # the same rows in words


def _idea(p: Proposal) -> IdeaOut:
    c = p.content
    return IdeaOut(
        id=p.id,
        status=p.status,
        created_at=p.created_at,
        title=c["title"],
        pattern=c["pattern"],
        why_it_matters=c["why_it_matters"],
        rule_sketch=c["rule_sketch"],
        evidence=c["evidence"],
        evidence_text=[row.get("text", "") for row in c["evidence"]],
    )


@router.get("/ai/finding-ideas")
def finding_ideas(ctx: CanReview) -> list[IdeaOut]:
    return [_idea(p) for p in discover.ideas(ctx)]


@router.post("/ai/finding-ideas")
def make_finding_ideas(
    ctx: CanReview, session: SessionDep, gateway: GatewayDep, today: TodayDep
) -> list[IdeaOut]:
    _release(session)
    if gateway is None:
        raise ModelUnavailableError("Ассистент пока не подключен")
    return [_idea(p) for p in discover.propose_ideas(gateway, ctx, today)]


class ColumnOut(BaseModel):
    field: str
    title: str
    header: str
    why: str


class MarkingOut(BaseModel):
    id: UUID
    template: str
    columns: list[ColumnOut]
    preview: dict[str, Any]  # the import read with this marking: rows, rows with errors, the first errors


class ProfileSavedOut(BaseModel):
    profile_id: UUID


@router.post("/imports/mapping")
async def make_marking(
    ctx: CanRead,
    session: SessionDep,
    gateway: GatewayDep,
    today: TodayDep,
    file: Annotated[UploadFile, File()],
    template: Annotated[str, Form()],
    restaurant_id: Annotated[UUID | None, Form()] = None,
) -> MarkingOut:
    """An unfamiliar file: the assistant marks its columns, the import checks the marking on the file."""
    _release(session)
    await run_in_threadpool(mapping.allowed, ctx, template, restaurant_id)  # access first, model or not
    if gateway is None:
        raise ModelUnavailableError("Ассистент пока не подключен")
    raw = await file.read(mapping.MAX_BYTES + 1)
    p, _ = await run_in_threadpool(
        mapping.propose_marking,
        gateway,
        ctx,
        template_name=template,
        restaurant_id=restaurant_id,
        filename=file.filename or "file",
        raw=raw,
        today=today,
    )
    titles = {c.name: c.title for c in TEMPLATES[p.content["template"]].columns}
    return MarkingOut(
        id=p.id,
        template=p.content["template"],
        columns=[ColumnOut(**c, title=titles.get(c["field"], c["field"])) for c in p.content["columns"]],
        preview=p.content["preview"],
    )


@router.post("/imports/mapping/{suggestion_id}/confirm")
def confirm_marking(suggestion_id: UUID, ctx: CanRead, today: TodayDep) -> ProfileSavedOut:
    """Confirmed once: later files with these headers load by it, through the whole validation."""
    return ProfileSavedOut(profile_id=mapping.confirm(ctx, suggestion_id, today=today))


def _release(session: Session) -> None:
    """The model may think for a minute: the request's transaction ends first (code review 28.10, p. 4)."""
    session.rollback()


class RebuildIn(BaseModel):
    restaurant_id: UUID | None = None  # none: the director's restaurant, or the network for the HQ


@router.post("/digests/rebuild", response_model=digests_api.DigestOut)
def rebuild_digest(
    body: RebuildIn, ctx: CanRead, gateway: GatewayDep, today: TodayDep
) -> digests_api.DigestOut:
    """«Пересобрать»: the digest of the last full week again, from the findings as they are now; the texts by
    the model when it is on (within the person's daily budget), by rules otherwise."""
    restaurant_id = digests_api.scope_of(ctx, body.restaurant_id)
    if not ctx.role.is_hq and restaurant_id != ctx.restaurant_id:
        raise NotFoundError("Сводки пока нет")  # another restaurant: the same answer as for a missing one
    if restaurant_id is not None:
        with user_session(ctx) as s:
            if s.get(Restaurant, restaurant_id) is None:
                raise NotFoundError("Ресторан не найден")
    write = digest_writer.writer(gateway, ctx) if gateway is not None else None
    week = digest_builder.Week.before(today)
    digest_id = digest_service.publish(ctx, restaurant_id=restaurant_id, week=week, today=today, write=write)
    with user_session(ctx) as s:
        digest = s.get(Digest, digest_id)
        assert digest is not None
        return digests_api.digest_out(digest)
