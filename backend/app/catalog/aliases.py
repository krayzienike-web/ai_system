"""Remembered name matches: see them, fix a wrong one, and find the files built on it."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import AliasKind, MenuItem, NameAlias, Product, Supplier
from app.core.errors import ForbiddenError, NotFoundError
from app.imports.models import BatchStatus, ImportBatch
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

TARGETS: dict[str, type[Product] | type[MenuItem] | type[Supplier]] = {
    AliasKind.PRODUCT: Product,
    AliasKind.MENU_ITEM: MenuItem,
    AliasKind.SUPPLIER: Supplier,
}


def _names(session: Session) -> dict[UUID, str]:
    out: dict[UUID, str] = {}
    for model in TARGETS.values():
        out.update({i: n for i, n in session.execute(select(model.id, model.name))})
    return out


def files_using(session: Session, alias: NameAlias) -> list[ImportBatch]:
    """Published files that resolved a name through this match (network-wide: any restaurant's files)."""
    tag = f"{alias.kind}:{alias.source_key}"
    query = select(ImportBatch).where(
        ImportBatch.status == BatchStatus.PUBLISHED, ImportBatch.aliases_used.contains([tag])
    )
    if alias.restaurant_id is not None:
        query = query.where(ImportBatch.restaurant_id == alias.restaurant_id)
    return list(session.execute(query.order_by(ImportBatch.created_at)).scalars())


def list_aliases(session: Session) -> list[dict[str, Any]]:
    names = _names(session)
    rows = session.execute(select(NameAlias).order_by(NameAlias.kind, NameAlias.source_text)).scalars()
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "source_text": a.source_text,
            "target_id": a.target_id,
            "target_name": names.get(a.target_id, "— позиция удалена из справочника"),
            "restaurant_id": a.restaurant_id,
            "created_at": a.created_at,
            "files": len(files_using(session, a)),
        }
        for a in rows
    ]


def _editable(session: Session, ctx: AccessContext, alias_id: UUID) -> NameAlias:
    alias = session.get(NameAlias, alias_id)
    if alias is None:
        raise NotFoundError("Соответствие не найдено")
    # The database refuses this too (RLS); the API says it in words.
    if alias.restaurant_id is None and not ctx.can(Permission.CATALOG_MANAGE):
        raise ForbiddenError("Соответствие для всей сети меняет только администратор управляющей компании")
    return alias


def change(
    session: Session, ctx: AccessContext, alias_id: UUID, target_id: UUID
) -> tuple[NameAlias, list[ImportBatch]]:
    alias = _editable(session, ctx, alias_id)
    if session.get(TARGETS[alias.kind], target_id) is None:
        raise NotFoundError("Позиция справочника не найдена")
    alias.target_id = target_id
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="alias.change",
        entity="name_alias",
        entity_id=alias.id,
    )
    return alias, files_using(session, alias)


def remove(session: Session, ctx: AccessContext, alias_id: UUID) -> list[ImportBatch]:
    alias = _editable(session, ctx, alias_id)
    affected = files_using(session, alias)
    session.delete(alias)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="alias.delete",
        entity="name_alias",
        entity_id=alias_id,
    )
    return affected
