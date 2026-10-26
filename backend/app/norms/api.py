from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import SessionDep, require
from app.norms import service
from app.norms.service import Norms
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

router = APIRouter(tags=["norms"])

CanRead = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]


class ReasonIO(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["loss", "planned", "shortage"]
    synonyms: list[str] = Field(default_factory=list, max_length=50)


class NormsIn(BaseModel):
    food_cost_target_pct: Decimal
    food_cost_by_category: dict[str, Decimal] = Field(default_factory=dict)
    loss_default_pct: Decimal
    loss_by_category: dict[str, Decimal] = Field(default_factory=dict)
    write_off_reasons: list[ReasonIO] = Field(default_factory=list, max_length=100)
    review_findings: bool = True  # engine findings are checked by HQ before directors see them


class NormsOut(NormsIn):
    menu_categories: list[str]  # what can be given its own food-cost target
    product_categories: list[str]  # what can be given its own loss allowance


def _out(norms: Norms, session: SessionDep) -> NormsOut:
    menu, products = service.categories(session)
    return NormsOut(
        food_cost_target_pct=norms.food_cost_target_pct,
        food_cost_by_category=norms.food_cost_by_category,
        loss_default_pct=norms.loss_default_pct,
        loss_by_category=norms.loss_by_category,
        write_off_reasons=[
            ReasonIO(code=r.code, title=r.title, kind=r.kind, synonyms=list(r.synonyms))
            for r in norms.reasons
        ],
        review_findings=norms.review_findings,
        menu_categories=menu,
        product_categories=products,
    )


@router.get("/settings/norms")
def get_norms(ctx: CanRead, session: SessionDep) -> NormsOut:
    return _out(service.load_norms(session), session)


@router.put("/settings/norms")
def put_norms(body: NormsIn, ctx: CanRead, session: SessionDep) -> NormsOut:
    norms = service.save_norms(session, ctx, body.model_dump(mode="json"))
    out = _out(norms, session)
    session.commit()
    return out
