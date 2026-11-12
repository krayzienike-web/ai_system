from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.analytics import runs
from app.catalog.models import AliasKind
from app.core.deps import SessionDep, require
from app.core.errors import NotFoundError
from app.core.period import TodayDep
from app.imports import service
from app.imports.models import ImportBatch, SourceProfile
from app.imports.templates import TEMPLATES
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["imports"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class TemplateColumnOut(BaseModel):
    title: str
    required: bool
    synonyms: list[str]


class TemplateOut(BaseModel):
    name: str
    title: str
    scope: str
    columns: list[TemplateColumnOut]
    one_of: list[list[str]]


class UnitFixOut(BaseModel):
    """A unit of the file the network has no factor for (Q35): set it, then «Проверить заново»."""

    product_id: UUID
    product_name: str
    unit: str
    unit_text: str
    base_unit: str
    rows: int  # rows of the file with this product and unit (among the errors shown)


def unit_fixes(errors: list[dict[str, Any]]) -> list[UnitFixOut]:
    out: dict[tuple[str, str], UnitFixOut] = {}
    for e in errors:
        fix = e.get("fix")
        if not fix or fix.get("kind") != "unit_factor":
            continue
        key = (fix["product_id"], fix["unit"])
        if key in out:
            out[key].rows += 1
        else:
            out[key] = UnitFixOut(**{k: v for k, v in fix.items() if k != "kind"}, rows=1)
    return list(out.values())


class BatchOut(BaseModel):
    id: UUID
    restaurant_id: UUID | None
    template: str
    filename: str
    status: str
    rows_total: int
    rows_valid: int
    period_from: date | None
    period_to: date | None
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    column_map: dict[str, str]
    unmatched: list[dict[str, Any]]
    aliases_used: list[str]
    created_at: datetime
    published_at: datetime | None

    # The file's columns were not recognised: the screen offers «Разметить с ИИ» (stage 5.5).
    markable: bool = False
    # Units without a factor, one per product and unit: the HQ sets them right on the report (Q35).
    unit_fixes: list[UnitFixOut] = Field(default_factory=list)

    @classmethod
    def of(cls, b: ImportBatch) -> "BatchOut":
        computed = {"markable", "unit_fixes"}
        fields = {name: getattr(b, name) for name in cls.model_fields if name not in computed}
        errors = b.errors or []
        return cls(
            **fields,
            markable=any(e.get("code") == "no_header" for e in errors),
            unit_fixes=unit_fixes(errors),
        )


@router.get("/imports/templates")
def list_templates(ctx: CanRead) -> list[TemplateOut]:
    return [
        TemplateOut(
            name=t.name,
            title=t.title,
            scope=t.scope,
            columns=[
                TemplateColumnOut(title=c.title, required=c.required, synonyms=list(c.synonyms[1:]))
                for c in t.columns
            ],
            one_of=[[t.column(n).title for n in g] for g in t.one_of],
        )
        for t in TEMPLATES.values()
    ]


@router.get("/imports")
def list_batches(ctx: CanRead, session: SessionDep) -> list[BatchOut]:
    rows = session.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(200)).scalars()
    return [BatchOut.of(b) for b in rows]


class FreshnessOut(BaseModel):
    restaurant_id: UUID
    template: str
    last_date: date | None
    status: str  # good | stale | missing


@router.get("/imports/freshness")
def get_freshness(ctx: CanRead, session: SessionDep, today: TodayDep) -> list[FreshnessOut]:
    return [FreshnessOut(**row) for row in service.freshness(session, today=today)]


class ProfileOut(BaseModel):
    id: UUID
    template: str
    restaurant_id: UUID | None  # none: the whole network
    title: str
    mapping: dict[str, str]


@router.get("/imports/profiles")
def source_profiles(ctx: CanRead, session: SessionDep) -> list[ProfileOut]:
    """The network's confirmed source profiles (docs/09): the exports that load without a template."""
    rows = session.execute(select(SourceProfile).order_by(SourceProfile.created_at.desc())).scalars()
    return [
        ProfileOut(
            id=p.id, template=p.template, restaurant_id=p.restaurant_id, title=p.title, mapping=p.mapping
        )
        for p in rows
    ]


@router.delete("/imports/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_profile(profile_id: UUID, ctx: CanRead, session: SessionDep) -> None:
    """A profile that reads files wrongly is removed (code review 02.11.2026, p. 5)."""
    service.delete_profile(session, ctx, profile_id)
    session.commit()


@router.get("/imports/{batch_id}")
def get_batch(batch_id: UUID, ctx: CanRead, session: SessionDep) -> BatchOut:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError("Загрузка не найдена")
    return BatchOut.of(batch)


@router.post("/imports", status_code=status.HTTP_201_CREATED)
async def upload(
    ctx: CanRead,
    session: SessionDep,
    today: TodayDep,
    file: Annotated[UploadFile, File()],
    # Omit to let the file say what it is (recognised by its header).
    template: Annotated[str | None, Form()] = None,
    restaurant_id: Annotated[UUID | None, Form()] = None,
) -> BatchOut:
    raw = await file.read(service.MAX_BYTES + 1)
    # Parsing up to 20 MB is synchronous work: keep it off the event loop.
    batch = await run_in_threadpool(
        service.upload,
        session,
        ctx,
        template_name=template,
        restaurant_id=restaurant_id,
        filename=file.filename or "file",
        raw=raw,
        today=today,
    )
    out = BatchOut.of(batch)
    session.commit()
    return out


class MatchIn(BaseModel):
    kind: AliasKind
    key: str = Field(min_length=1, max_length=300)
    target_id: UUID


class MatchesIn(BaseModel):
    matches: list[MatchIn] = Field(min_length=1, max_length=500)


class CatalogOption(BaseModel):
    id: UUID
    code: str
    name: str
    base_unit: str | None = None  # products only: what a unit factor converts to


@router.get("/catalog/{kind}")
def list_catalog(kind: AliasKind, ctx: CanRead, session: SessionDep) -> list[CatalogOption]:
    return [CatalogOption(**o) for o in service.catalog_options(session, kind)]


@router.post("/imports/{batch_id}/match")
def match(batch_id: UUID, body: MatchesIn, ctx: CanRead, session: SessionDep, today: TodayDep) -> BatchOut:
    batch = service.match(
        session, ctx, batch_id, [(m.kind, m.key, m.target_id) for m in body.matches], today=today
    )
    out = BatchOut.of(batch)
    session.commit()
    return out


@router.post("/imports/{batch_id}/recheck")
def recheck(batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> BatchOut:
    """A file that failed checked again with today's reference: after a unit factor was set (Q35)."""
    out = BatchOut.of(service.recheck(session, ctx, batch_id, today=today))
    session.commit()
    return out


@router.post("/imports/{batch_id}/publish")
def publish(
    batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep, background: BackgroundTasks
) -> BatchOut:
    out = BatchOut.of(service.publish(session, ctx, batch_id, today=today))
    run = runs.request(session, ctx)  # the findings follow the data: recomputed after the commit
    session.commit()
    runs.dispatch(run, today, background)
    return out


@router.post("/imports/{batch_id}/reprocess")
def reprocess(
    batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep, background: BackgroundTasks
) -> BatchOut:
    out = BatchOut.of(service.reprocess(session, ctx, batch_id, today=today))
    run = runs.request(session, ctx)  # the findings follow the data: recomputed after the commit
    session.commit()
    runs.dispatch(run, today, background)
    return out


@router.post("/imports/{batch_id}/rollback")
def rollback(
    batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep, background: BackgroundTasks
) -> BatchOut:
    out = BatchOut.of(service.rollback(session, ctx, batch_id, today=today))
    run = runs.request(session, ctx)  # the findings follow the data: recomputed after the commit
    session.commit()
    runs.dispatch(run, today, background)
    return out
