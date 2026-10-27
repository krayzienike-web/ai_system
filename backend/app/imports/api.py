from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.catalog.models import AliasKind
from app.core.deps import SessionDep, require
from app.core.errors import NotFoundError
from app.core.period import TodayDep
from app.imports import service
from app.imports.models import ImportBatch
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

    @classmethod
    def of(cls, b: ImportBatch) -> "BatchOut":
        return cls(**{name: getattr(b, name) for name in cls.model_fields})


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


@router.post("/imports/{batch_id}/publish")
def publish(batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> BatchOut:
    out = BatchOut.of(service.publish(session, ctx, batch_id, today=today))
    session.commit()
    return out


@router.post("/imports/{batch_id}/reprocess")
def reprocess(batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> BatchOut:
    out = BatchOut.of(service.reprocess(session, ctx, batch_id, today=today))
    session.commit()
    return out


@router.post("/imports/{batch_id}/rollback")
def rollback(batch_id: UUID, ctx: CanRead, session: SessionDep, today: TodayDep) -> BatchOut:
    out = BatchOut.of(service.rollback(session, ctx, batch_id, today=today))
    session.commit()
    return out
