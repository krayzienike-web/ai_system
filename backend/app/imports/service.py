"""Import pipeline: upload → validate → publish (idempotent replace) → rollback. docs/04-data-import.md."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.catalog.aliases import TARGETS
from app.catalog.models import MenuItem, NameAlias, Product, RecipeLine, Supplier
from app.catalog.recipes import Line, find_cycle, lines_on
from app.core.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from app.core.period import last_full_week_end
from app.imports.matching import normalize, suggest
from app.imports.models import BatchStatus, ImportBatch
from app.imports.reader import detect_template, read_table
from app.imports.templates import TEMPLATES, Scope, Template
from app.imports.validate import Lookups, Ref, Result, validate
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

MAX_BYTES = 20 * 1024 * 1024
FACTS: dict[str, type[Sale] | type[Receipt] | type[WriteOff] | type[InventoryCount] | type[Transfer]] = {
    "sales": Sale,
    "transfers": Transfer,
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


def load_lookups(session: Session, restaurant_id: UUID | None = None) -> Lookups:
    cache: dict[str, UUID | None] = {}

    def resolve_restaurant(text_value: str) -> UUID | None:
        if text_value not in cache:
            cache[text_value] = session.execute(
                text("SELECT app.resolve_restaurant(:t)"), {"t": text_value}
            ).scalar_one()
        return cache[text_value]

    lk = Lookups(resolve_restaurant=resolve_restaurant, own_restaurant_id=restaurant_id)
    for p in session.execute(select(Product)).scalars():
        ref = Ref(p.id, p.name, p.base_unit, p.is_semi)
        lk.products[p.code] = ref
        lk.product_names.setdefault(normalize(p.name), ref)
    for m in session.execute(select(MenuItem)).scalars():
        ref = Ref(m.id, m.name)
        lk.menu_items[m.code] = ref
        lk.menu_item_names.setdefault(normalize(m.name), ref)
    for s in session.execute(select(Supplier)).scalars():
        ref = Ref(s.id, s.name)
        lk.suppliers[s.code] = ref
        lk.supplier_names.setdefault(normalize(s.name), ref)
    refs = {
        "product": {r.id: r for r in lk.products.values()},
        "menu_item": {r.id: r for r in lk.menu_items.values()},
        "supplier": {r.id: r for r in lk.suppliers.values()},
    }
    # Network-wide matches first, then this restaurant's own ones on top.
    aliases = session.execute(
        select(NameAlias)
        .where((NameAlias.restaurant_id.is_(None)) | (NameAlias.restaurant_id == restaurant_id))
        .order_by(NameAlias.restaurant_id.is_not(None))
    ).scalars()
    for a in aliases:
        target = refs[a.kind].get(a.target_id)
        if target is not None:
            lk.aliases[(a.kind, a.source_key)] = target
    return lk


def _options(lk: Lookups, kind: str) -> list[tuple[UUID, str]]:
    by_code = {"product": lk.products, "menu_item": lk.menu_items, "supplier": lk.suppliers}[kind]
    return [(r.id, r.name) for r in by_code.values()]


def _unmatched_json(result: Result, lk: Lookups) -> list[dict[str, Any]]:
    return [
        {
            "kind": u.kind,
            "code": u.code,
            "name": u.name,
            "key": u.key,
            "rows": u.rows[:20],
            "rows_count": len(u.rows),
            "candidates": [
                {"id": str(c.id), "name": c.name, "score": c.score}
                for c in suggest(u.name or u.code or "", _options(lk, u.kind))
            ],
        }
        for u in result.unmatched
    ]


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
    session: Session, template: Template, raw: bytes, filename: str, today: date, restaurant_id: UUID | None
) -> tuple[Result | None, list[dict[str, Any]], dict[str, str], Lookups]:
    lk = load_lookups(session, restaurant_id)
    try:
        table = read_table(raw, filename, template)
    except InvalidError as e:
        return None, [{"row": None, "column": None, "message": str(e)}], {}, lk
    column_map = {template.column(k).title: str(v + 1) for k, v in table.column_map.items()}
    return validate(template, table, lk, today=today), [], column_map, lk


def _apply(batch: ImportBatch, result: Result | None, file_errors: list[dict[str, Any]], lk: Lookups) -> None:
    """Writes the validation report onto the batch and decides its status."""
    if result is None:
        batch.status, batch.errors, batch.unmatched = BatchStatus.FAILED, file_errors, []
        return
    batch.rows_total = result.rows_total
    batch.rows_valid = len(result.records)
    batch.errors = [e.as_dict() for e in result.errors]
    batch.warnings = [w.as_dict() for w in result.warnings]
    batch.unmatched = _unmatched_json(result, lk)
    batch.period_from, batch.period_to = result.period_from, result.period_to
    # Any blocking error fails the whole file: publishing half a file would silently distort the numbers.
    if result.errors:
        batch.status = BatchStatus.FAILED
    elif result.unmatched:
        batch.status = BatchStatus.NEEDS_MATCHING
    elif result.records or result.skipped:
        # A file of only incoming transfers is fine: those rows are counted from the sender's file.
        batch.status = BatchStatus.VALIDATED
    else:
        batch.status = BatchStatus.FAILED
        batch.errors = [{"row": None, "column": None, "message": "В файле нет строк с данными"}]


def upload(
    session: Session,
    ctx: AccessContext,
    *,
    template_name: str | None,
    restaurant_id: UUID | None,
    filename: str,
    raw: bytes,
    today: date,
) -> ImportBatch:
    if not raw:
        raise InvalidError("Файл пустой")
    if len(raw) > MAX_BYTES:
        raise InvalidError("Файл больше 20 МБ — разбейте выгрузку на несколько периодов")
    if template_name is None:
        # The file says what it is: restaurant facts when a restaurant is chosen, reference data otherwise.
        scope = Scope.RESTAURANT if restaurant_id is not None else Scope.NETWORK
        template = detect_template(raw, filename, [t for t in TEMPLATES.values() if t.scope is scope])
    else:
        template = _template(template_name)
    _check_access(session, ctx, template, restaurant_id)
    sha = hashlib.sha256(raw).hexdigest()
    duplicate = session.execute(
        select(ImportBatch.id).where(
            ImportBatch.sha256 == sha,
            ImportBatch.template == template.name,
            # The same file for another restaurant is not a duplicate (a transfer exported by both sides).
            ImportBatch.restaurant_id.is_(None)
            if restaurant_id is None
            else ImportBatch.restaurant_id == restaurant_id,
            ImportBatch.status.in_([BatchStatus.VALIDATED, BatchStatus.PUBLISHED]),
        )
    ).first()
    if duplicate:
        raise ConflictError("Этот файл уже загружен для этого ресторана")

    result, file_errors, column_map, lk = _run(session, template, raw, filename, today, restaurant_id)
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
    _apply(batch, result, file_errors, lk)
    if template.name == "recipes" and result is not None and batch.status == BatchStatus.VALIDATED:
        cycle = recipe_cycle(session, result.records)
        if cycle:
            batch.status = BatchStatus.FAILED
            batch.errors = [{"row": None, "column": None, "message": cycle}]
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


def _parent(record: dict[str, Any]) -> UUID:
    parent: UUID = record["menu_item_id"] or record["semi_product_id"]
    return parent


def recipe_cycle(session: Session, records: list[dict[str, Any]]) -> str | None:
    """Would the recipes in the file, together with the stored ones, make a semi-finished product contain
    itself? Checked on every date a recipe version starts. Returns the chain in words, or None."""
    new_versions = {(_parent(r), r["valid_from"]) for r in records}
    lines = [
        Line(row.menu_item_id or row.semi_product_id, row.product_id, row.gross_qty, row.valid_from)  # type: ignore[arg-type]
        for row in session.execute(select(RecipeLine)).scalars()
        if ((row.menu_item_id or row.semi_product_id), row.valid_from) not in new_versions
    ] + [Line(_parent(r), r["product_id"], r["gross_qty"], r["valid_from"]) for r in records]
    names = {p.id: p.name for p in session.execute(select(Product)).scalars()}
    for day in sorted({line.valid_from for line in lines}):
        cycle = find_cycle(lines_on(lines, day))
        if cycle:
            chain = " → ".join(f"«{names.get(node, node)}»" for node in cycle)
            return f"Полуфабрикат входит сам в себя: {chain}. Исправьте техкарты"
    return None


def _publish_reference(
    session: Session, batch: ImportBatch, template: Template, records: list[dict[str, Any]]
) -> None:
    if template.name == "recipes":
        cycle = recipe_cycle(session, records)
        if cycle:
            raise InvalidError(cycle)
        # A recipe version (dish or semi-finished product × valid_from) in the file replaces the same version.
        for parent, valid_from in {(_parent(r), r["valid_from"]) for r in records}:
            session.execute(
                delete(RecipeLine).where(
                    (RecipeLine.menu_item_id == parent) | (RecipeLine.semi_product_id == parent),
                    RecipeLine.valid_from == valid_from,
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
    _write(session, batch, template, today)
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
        payload={"rows": batch.rows_valid},
    )
    return batch


def reprocess(session: Session, ctx: AccessContext, batch_id: UUID, *, today: date) -> ImportBatch:
    """Loads an already published file again with today's reference data and matches —
    after a wrong match was fixed. Its rows are replaced, nothing is duplicated."""
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError("Загрузка не найдена")
    template = _template(batch.template)
    _check_access(session, ctx, template, batch.restaurant_id)
    if batch.status != BatchStatus.PUBLISHED:
        raise InvalidError("Пересчитать можно только загруженный файл")
    _write(session, batch, template, today)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="import.reprocess",
        entity="import_batch",
        entity_id=batch.id,
    )
    return batch


def _write(session: Session, batch: ImportBatch, template: Template, today: date) -> None:
    # Validate again: reference data and matches may have changed since the upload.
    result, _, _, lk = _run(session, template, batch.raw, batch.filename, today, batch.restaurant_id)
    if result is None or result.errors or result.unmatched:
        raise InvalidError("Файл больше не проходит проверку — загрузите его заново, отчет покажет почему")
    batch.rows_valid = len(result.records)
    batch.aliases_used = sorted(lk.used)
    if template.scope is Scope.NETWORK:
        _publish_reference(session, batch, template, result.records)
    else:
        model = FACTS[template.name]
        # Idempotent: the restaurant's rows of this type for the file's period are replaced, never duplicated.
        # A file with no rows of its own (only incoming transfers) has no period and replaces nothing.
        if batch.period_from is not None and batch.period_to is not None:
            session.execute(
                delete(model).where(
                    model.restaurant_id == batch.restaurant_id,
                    model.day >= batch.period_from,
                    model.day <= batch.period_to,
                )
            )
        if result.records:
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


FRESHNESS_TEMPLATES = ("sales", "receipts", "write_offs", "inventory_counts")


def freshness(session: Session, *, today: date) -> list[dict[str, Any]]:
    """For every visible restaurant and kind of facts: data up to which day, and whether that is enough.

    Up to date = there is data within the last full week (purchases and write-offs do not happen every day);
    stock counts are periodic, so for them only "missing" is flagged.
    """
    rows = session.execute(
        select(ImportBatch.restaurant_id, ImportBatch.template, func.max(ImportBatch.period_to))
        .where(ImportBatch.status == BatchStatus.PUBLISHED, ImportBatch.restaurant_id.is_not(None))
        .group_by(ImportBatch.restaurant_id, ImportBatch.template)
    )
    last = {(restaurant_id, template): day for restaurant_id, template, day in rows}
    week_start = last_full_week_end(today) - timedelta(days=6)
    out = []
    for r in session.execute(select(Restaurant).order_by(Restaurant.code)).scalars():
        for template in FRESHNESS_TEMPLATES:
            day = last.get((r.id, template))
            if day is None:
                status = "missing"
            elif template == "inventory_counts" or day >= week_start:
                status = "good"
            else:
                status = "stale"
            out.append({"restaurant_id": r.id, "template": template, "last_date": day, "status": status})
    return out


def match(
    session: Session, ctx: AccessContext, batch_id: UUID, matches: list[tuple[str, str, UUID]], *, today: date
) -> ImportBatch:
    """Remembers what each unknown name in the file is, then checks the file again.

    `matches` are (kind, key from the report, catalog id). An HQ admin's match applies to the whole
    network; anyone else's — only to the restaurant of the file.
    """
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError("Загрузка не найдена")
    template = _template(batch.template)
    _check_access(session, ctx, template, batch.restaurant_id)
    if batch.status != BatchStatus.NEEDS_MATCHING:
        raise InvalidError("В этом файле нечего сопоставлять")
    known = {(u["kind"], u["key"]): u for u in batch.unmatched}
    network_wide = ctx.can(Permission.CATALOG_MANAGE) or batch.restaurant_id is None
    scope = None if network_wide else batch.restaurant_id
    for kind, key, target_id in matches:
        item = known.get((kind, key))
        if item is None:
            raise InvalidError(f"В отчете нет названия «{key}»")
        if session.get(TARGETS[kind], target_id) is None:
            raise NotFoundError("Позиция справочника не найдена")
        existing = session.execute(
            select(NameAlias).where(
                NameAlias.kind == kind,
                NameAlias.source_key == key,
                NameAlias.restaurant_id.is_(None) if scope is None else NameAlias.restaurant_id == scope,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                NameAlias(
                    tenant_id=ctx.tenant_id,
                    restaurant_id=scope,
                    kind=kind,
                    source_key=key,
                    source_text=(item["name"] or item["code"] or key)[:300],
                    target_id=target_id,
                    created_by=ctx.user_id,
                )
            )
        else:
            existing.target_id = target_id
    session.flush()
    result, file_errors, _, lk = _run(
        session, template, batch.raw, batch.filename, today, batch.restaurant_id
    )
    _apply(batch, result, file_errors, lk)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="import.match",
        entity="import_batch",
        entity_id=batch.id,
        payload={"matches": len(matches), "network_wide": network_wide},
    )
    return batch


def catalog_options(session: Session, kind: str) -> list[dict[str, Any]]:
    model = TARGETS.get(kind)
    if model is None:
        raise InvalidError(f"Неизвестный справочник «{kind}»")
    rows = session.execute(select(model.id, model.code, model.name).order_by(model.name)).all()
    return [{"id": i, "code": c, "name": n} for i, c, n in rows]
