from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.catalog import aliases
from app.core.deps import SessionDep, require
from app.imports.models import ImportBatch
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["catalog"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class AliasOut(BaseModel):
    id: UUID
    kind: str
    source_text: str
    target_id: UUID
    target_name: str
    restaurant_id: UUID | None  # None: for the whole network
    created_at: datetime
    files: int  # published files built on this match


class FileRef(BaseModel):
    id: UUID
    filename: str
    template: str
    restaurant_id: UUID | None


class AliasChangeIn(BaseModel):
    target_id: UUID


class AliasChangeOut(BaseModel):
    # Files loaded with the old match: re-process them so the numbers follow the fix.
    affected_files: list[FileRef]


def _refs(batches: list[ImportBatch]) -> list[FileRef]:
    return [
        FileRef(id=b.id, filename=b.filename, template=b.template, restaurant_id=b.restaurant_id)
        for b in batches
    ]


@router.get("/aliases")
def list_aliases(ctx: CanRead, session: SessionDep) -> list[AliasOut]:
    return [AliasOut(**row) for row in aliases.list_aliases(session)]


@router.put("/aliases/{alias_id}")
def change_alias(alias_id: UUID, body: AliasChangeIn, ctx: CanRead, session: SessionDep) -> AliasChangeOut:
    _, affected = aliases.change(session, ctx, alias_id, body.target_id)
    out = AliasChangeOut(affected_files=_refs(affected))
    session.commit()
    return out


@router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: UUID, ctx: CanRead, session: SessionDep) -> AliasChangeOut:
    out = AliasChangeOut(affected_files=_refs(aliases.remove(session, ctx, alias_id)))
    session.commit()
    return out
