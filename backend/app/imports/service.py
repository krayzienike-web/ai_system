"""Import pipeline: upload → validate → publish (idempotent replace) → rollback. docs/04-data-import.md."""

import hashlib
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.catalog.models import MenuItem, Product, RecipeLine, Supplier
from app.core.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from app.imports.models import BatchStatus, ImportBatch
from app.imports.reader import read_table
from app.imports.templates import TEMPLATES, Scope, Template
from app.imports.validate import Lookups, Ref, Result, validate
from app.operations.models import InventoryCount, Receipt, Sale, WriteOff
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

MAX_BYTES = 20 * 1024 * 1024
FACTS: dict[str, type[Sale] | type[Receipt] | type[WriteOff] | type[InventoryCount]] = {
    "sales": Sale,
    "receipts": Receipt,
    "write_offs": WriteOff,
    "inventory_counts": InventoryCount,
}
REFERENCE: dict[str, type[Product] | type[Supplier] | type[MenuItem] | type[Restaurant]] = {
    "products": Product,
    "suppliers": Supplier,
    "menu_items": MenuItem,
    "restaurants": Restaurant,
}


def load_lookups(session: Session) -> Lookups:
    lk = Lookups()
    for p in session.execute(select(Product)).scalars():
        ref = Ref(p.id, p.name, p.base_unit)
        lk.products[p.code] = ref
        lk.product_names.setdefault(p.name.lower(), ref)
    for m in session.execute(select(MenuItem)).scalars():
        ref = Ref(m.id, m.name)
        lk.menu_items[m.code] = ref
        lk.menu_item_names.setdefault(m.name.lower(), ref)
    for s in session.execute(select(Supplier)).scalars():
        ref = Ref(s.id, s.name)
        lk.suppliers[s.code] = ref
        lk.supplier_names.setdefault(s.name.lower(), ref)
    return lk


def _template(name: str) -> Template:
    template = TEMPLATES.get(name)
    if template is None:
        raise InvalidError(f"Неизвестный шаблон «{name}»")
    return template


def _check_access(
    session: Session, ctx: AccessContext, template: Template, restaurant_id: UUID | None
) -> None:
    if template.scope is Scope.NETWORK:
        needed = (
            Permission.RESTAURANTS_MANAGE if template.name == "restaurants" else Permission.CATALOG_MANAGE
        )
        if not ctx.can(needed):
            raise ForbiddenError("Справочники сети загружает управляющая компания")
        if restaurant_id is not None:
            raise InvalidError("Справочник загружается для всей сети, без ресторана")
        return
    if not ctx.can(Permission.DATA_UPLOAD):
        raise ForbiddenError("Нет права загружать данные")
    if restaurant_id is None:
        raise InvalidError("Выберите ресторан, к которому относится файл")
    # Row-level security: a director "sees" only their own restaurant.
    if session.get(Restaurant, restaurant_id) is None:
        raise NotFoundError("Ресторан не найден")


def _run(
    session: Session, template: Template, raw: bytes, filename: str, today: date
) -> tuple[Result | None, list[dict[str, Any]], dict[str, str]]:
    try:
        table = read_table(raw, filename, template)
    except InvalidError as e:
        return None, [{"row": None, "column": None, "message": str(e)}], {}
    column_map = {template.column(k).title: str(v + 1) for k, v in table.column_map.items()}
    return validate(template, table, load_lookups(session), today=today), [], column_map


def upload(
    session: Session,
    ctx: AccessContext,
    *,
    template_name: str,
    restaurant_id: UUID | None,
    filename: str,
    raw: bytes,
    today: date,
) -> ImportBatch:
    template = _template(template_name)
    _check_access(session, ctx, template, restaurant_id)
    if not raw:
        raise InvalidError("Файл пустой")
    if len(raw) > MAX_BYTES:
        raise InvalidError("Файл больше 20 МБ — разбейте выгрузку на несколько периодов")
    sha = hashlib.sha256(raw).hexdigest()
    duplicate = session.execute(
        select(ImportBatch.id).where(
            ImportBatch.sha256 == sha,
            ImportBatch.template == template.name,
            ImportBatch.status.in_([BatchStatus.VALIDATED, BatchStatus.PUBLISHED]),
        )
    ).first()
    if duplicate:
        raise ConflictError("Этот файл уже загружен")

    result, file_errors, column_map = _run(session, template, raw, filename, today)
    batch = ImportBatch(
        tenant_id=ctx.tenant_id,
        restaurant_id=restaurant_id,
        template=template.name,
        filename=filename[:300],
        sha256=sha,
        raw=raw,
        column_map=column_map,
        created_by=ctx.user_id,
    )
    if result is None:
        batch.status, batch.errors = BatchStatus.FAILED, file_errors
    else:
        batch.rows_total = result.rows_total
        batch.rows_valid = len(result.records)
        batch.errors = [e.as_dict() for e in result.errors]
        batch.warnings = [w.as_dict() for w in result.warnings]
        batch.period_from, batch.period_to = result.period_from, result.period_to
        # Any blocking error fails the whole file: publishing half a file would silently distort the numbers.
        ok = not result.errors and result.records
        batch.status = BatchStatus.VALIDATED if ok else BatchStatus.FAILED
        if not result.records and not result.errors:
            batch.errors = [{"row": None, "column": None, "message": "В файле нет строк с данными"}]
    session.add(batch)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="import.upload",
        entity="import_batch",
        entity_id=batch.id,
        payload={"template": template.name, "status": batch.status},
    )
    return batch


def _publish_reference(
    session: Session, batch: ImportBatch, template: Template, records: list[dict[str, Any]]
) -> None:
    if template.name == "recipes":
        # A recipe version (menu item × valid_from) in the file replaces the same version in full.
        versions = {(r["menu_item_id"], r["valid_from"]) for r in records}
        for menu_item_id, valid_from in versions:
            session.execute(
                delete(RecipeLine).where(
                    RecipeLine.menu_item_id == menu_item_id, RecipeLine.valid_from == valid_from
                )
            )
        session.execute(insert(RecipeLine), [{**r, "tenant_id": batch.tenant_id} for r in records])
        return
    model = REFERENCE[template.name]
    rows = list(
        {r["code"]: {**r, "tenant_id": batch.tenant_id} for r in records}.values()
    )  # last row per code wins
    stmt = pg_insert(model).values(rows)
    updates = {k: stmt.excluded[k] for k in rows[0] if k not in ("code", "tenant_id")}
    session.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "code"], set_=updates))


def publish(session: Session, ctx: AccessContext, batch_id: UUID, *, today: date) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError("Загрузка не найдена")
    template = _template(batch.template)
    _check_access(session, ctx, template, batch.restaurant_id)
    if batch.status != BatchStatus.VALIDATED:
        raise InvalidError("Опубликовать можно только проверенный файл без ошибок")
    # Validate again: reference data may have changed since the upload.
    result, _, _ = _run(session, template, batch.raw, batch.filename, today)
    if result is None or result.errors:
        raise InvalidError("Файл больше не проходит проверку — загрузите его заново")

    if template.scope is Scope.NETWORK:
        _publish_reference(session, batch, template, result.records)
    else:
        model = FACTS[template.name]
        # Idempotent: the restaurant's rows of this type for the file's period are replaced, never duplicated.
        session.execute(
            delete(model).where(
                model.restaurant_id == batch.restaurant_id,
                model.day >= batch.period_from,
                model.day <= batch.period_to,
            )
        )
        session.execute(
            insert(model),
            [
                {
                    **r,
                    "tenant_id": batch.tenant_id,
                    "restaurant_id": batch.restaurant_id,
                    "import_batch_id": batch.id,
                }
                for r in result.records
            ],
        )
    batch.status = BatchStatus.PUBLISHED
    batch.published_at = datetime.now(UTC)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="import.publish",
        entity="import_batch",
        entity_id=batch.id,
        payload={"rows": len(result.records)},
    )
    return batch


def rollback(session: Session, ctx: AccessContext, batch_id: UUID) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError("Загрузка не найдена")
    template = _template(batch.template)
    _check_access(session, ctx, template, batch.restaurant_id)
    if batch.status != BatchStatus.PUBLISHED:
        raise InvalidError("Откатить можно только опубликованный файл")
    if template.scope is Scope.NETWORK:
        raise InvalidError("Справочник не откатывается — загрузите исправленный файл")
    model = FACTS[template.name]
    session.execute(delete(model).where(model.import_batch_id == batch.id))
    batch.status = BatchStatus.ROLLED_BACK
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="import.rollback",
        entity="import_batch",
        entity_id=batch.id,
    )
    return batch
