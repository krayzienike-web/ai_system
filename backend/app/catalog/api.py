from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.catalog import aliases, units
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


class UnitFactorOut(BaseModel):
    id: UUID
    product_id: UUID
    product_code: str
    product_name: str
    base_unit: str
    unit: str  # normalised: how the import compares it
    unit_text: str  # as the export writes it
    factor: Decimal  # base units in one `unit_text`
    files: int  # published files converted by it
    created_at: datetime


class UnitFactorIn(BaseModel):
    product_id: UUID
    unit_text: str = Field(min_length=1, max_length=40)
    factor: str = Field(min_length=1, max_length=30)  # «2,5» as a person types it: the service reads it


class UnitFactorSaved(BaseModel):
    factor: UnitFactorOut
    # Files loaded with the old value: re-process them so the numbers follow the change.
    affected_files: list[FileRef]


@router.get("/settings/units")
def list_unit_factors(ctx: CanRead, session: SessionDep) -> list[UnitFactorOut]:
    return [UnitFactorOut(**row) for row in units.list_factors(session)]


@router.put("/settings/units")
def save_unit_factor(body: UnitFactorIn, ctx: CanRead, session: SessionDep) -> UnitFactorSaved:
    row, affected = units.save(
        session, ctx, product_id=body.product_id, unit_text=body.unit_text, factor=body.factor
    )
    out = UnitFactorSaved(factor=UnitFactorOut(**row), affected_files=_refs(affected))
    session.commit()
    return out


@router.delete("/settings/units/{factor_id}")
def delete_unit_factor(factor_id: UUID, ctx: CanRead, session: SessionDep) -> AliasChangeOut:
    out = AliasChangeOut(affected_files=_refs(units.remove(session, ctx, factor_id)))
    session.commit()
    return out
