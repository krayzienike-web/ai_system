"""Units of the exports per product (Q35): «1 упак Моцареллы = 2,5 кг». The HQ admin keeps the list for the
whole network in «Нормы и настройки»; an import converts by it and never guesses a unit it does not know.
A changed or removed factor names the published files built on it, to re-process them."""

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Product, UnitFactor
from app.core.errors import ForbiddenError, InvalidError, NotFoundError
from app.imports.matching import normalize
from app.imports.models import BatchStatus, ImportBatch
from app.imports.validate import unit_of
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

MAX_FACTOR = Decimal(10_000)  # base units in one unit: a box of 10 000 kg is a typo
TITLES = {"kg": "кг", "l": "л", "pcs": "шт"}


def tag(product_id: UUID, unit: str) -> str:
    """How a file remembers it relied on a factor (`ImportBatch.aliases_used`)."""
    return f"unit:{product_id}:{unit}"


def files_using(session: Session, f: UnitFactor) -> list[ImportBatch]:
    return list(
        session.execute(
            select(ImportBatch)
            .where(
                ImportBatch.status == BatchStatus.PUBLISHED,
                ImportBatch.aliases_used.contains([tag(f.product_id, f.unit)]),
            )
            .order_by(ImportBatch.created_at)
        ).scalars()
    )


def _row(session: Session, f: UnitFactor, product: Product) -> dict[str, Any]:
    return {
        "id": f.id,
        "product_id": f.product_id,
        "product_code": product.code,
        "product_name": product.name,
        "base_unit": product.base_unit,
        "unit": f.unit,
        "unit_text": f.unit_text,
        "factor": f.factor.normalize(),
        "files": len(files_using(session, f)),
        "created_at": f.created_at,
    }


def list_factors(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(UnitFactor, Product)
        .join(Product, Product.id == UnitFactor.product_id)
        .order_by(Product.name, UnitFactor.unit)
    ).all()
    return [_row(session, f, p) for f, p in rows]


def _may(ctx: AccessContext) -> None:
    if not ctx.can(Permission.NORMS_MANAGE):
        raise ForbiddenError("Единицы в выгрузках задает администратор управляющей компании")


def _factor(value: Decimal | str) -> Decimal:
    try:
        factor = Decimal(str(value).replace(",", ".").strip())
    except InvalidOperation:
        raise InvalidError("Коэффициент — число, например 2,5") from None
    if not factor.is_finite() or factor <= 0:
        raise InvalidError("Коэффициент должен быть больше нуля")
    if factor > MAX_FACTOR:
        raise InvalidError("Коэффициент больше 10 000 — проверьте, та ли единица")
    if factor != factor.quantize(Decimal("0.000001")):
        raise InvalidError("Коэффициент — не больше шести знаков после запятой")
    return factor


def save(
    session: Session, ctx: AccessContext, *, product_id: UUID, unit_text: str, factor: Decimal | str
) -> tuple[dict[str, Any], list[ImportBatch]]:
    """Adds the factor or changes it (one per product and unit). Returns it and the published files that
    were loaded with the old value — they need «Пересчитать» to follow the change."""
    _may(ctx)
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Товар не найден в справочнике")
    text = unit_text.strip()
    unit = normalize(text)
    if not unit:
        raise InvalidError("Укажите единицу, как она написана в выгрузке, например «упак»")
    if len(text) > 40:
        raise InvalidError("Единица — не длиннее 40 символов")
    standard = unit_of(text)
    if standard is not None and standard[0] == product.base_unit:
        raise InvalidError(f"«{text}» и так переводится в {TITLES[product.base_unit]} — коэффициент не нужен")
    value = _factor(factor)
    stmt = (
        insert(UnitFactor)
        .values(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            unit=unit,
            unit_text=text,
            factor=value,
            created_by=ctx.user_id,
        )
        .on_conflict_do_update(
            constraint="one_factor_per_unit",
            set_={"factor": value, "unit_text": text, "created_by": ctx.user_id},
        )
        .returning(UnitFactor.id)
    )
    factor_id = session.execute(stmt).scalar_one()
    session.expire_all()
    f = session.get(UnitFactor, factor_id)
    assert f is not None
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="unit_factor.save",
        entity="unit_factor",
        entity_id=f.id,
        payload={"product": product.code, "unit": unit, "factor": str(value)},
    )
    return _row(session, f, product), files_using(session, f)


def remove(session: Session, ctx: AccessContext, factor_id: UUID) -> list[ImportBatch]:
    _may(ctx)
    f = session.get(UnitFactor, factor_id)
    if f is None:
        raise NotFoundError("Коэффициент не найден")
    affected = files_using(session, f)
    session.delete(f)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="unit_factor.delete",
        entity="unit_factor",
        entity_id=factor_id,
    )
    return affected
