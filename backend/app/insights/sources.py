"""«Откуда цифры» до документа: the uploaded rows behind a finding (docs/06, stage 4).

A finding names what it is about: a product or a dish, a restaurant or the whole network, a period. The rows
of the loaded files about the same thing in the same period are its documents: invoices, stock counts,
write-offs, transfers, sales. Each row says which file it came from.

Access is the finding's own: the finding is read the way its card is (a director gets only checked findings of
their restaurant), and the fact rows are read under row-level security, so a director never gets another
restaurant's rows even for a product the whole network buys. Nothing here computes a figure of the finding:
the rows are shown as loaded; the check of the figure is the review's «Расчет по шагам».
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.catalog.models import MenuItem, Product, Supplier
from app.imports.models import ImportBatch
from app.imports.validate import UNIT_TITLES
from app.insights import service
from app.insights.models import Finding
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tenancy.models import Restaurant

LIMIT = 200  # rows per kind of document; the rest is counted, not sent
GAP_LOOKBACK_DAYS = 14  # a missing upload: the restaurant's last invoices before the gap


@dataclass
class Column:
    key: str
    label: str
    type: str  # text | date | qty | money


@dataclass
class Group:
    kind: str  # receipts | counts | write_offs | transfers | sales
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    total: int  # rows that match, `rows` holds at most LIMIT of them
    same: list[str] = field(default_factory=list)  # values every row shares, said once instead of a column


@dataclass
class Sources:
    note: str
    groups: list[Group] = field(default_factory=list)


@dataclass
class _Scope:
    restaurant_id: UUID | None  # None: every restaurant the caller sees (network findings — HQ only)
    date_from: date
    date_to: date
    products: list[UUID] | None  # None: the finding is not about given products (a missed count, a gap)
    dishes: list[UUID] | None


def _scope(session: Session, f: Finding) -> tuple[_Scope, set[str]]:
    """What the finding is about and which documents tell its story."""
    ev = f.evidence or {}
    kind = ev.get("kind")
    # The products the finding names. A code no longer in the catalogue gives no rows rather than every row
    # of the restaurant. «paper» keys its `products` by count day, so only «mixed_up» names products there.
    codes: list[str] | None = None
    if isinstance(ev.get("product"), str):
        codes = [ev["product"]]
    elif kind == "mixed_up" and isinstance(ev.get("products"), dict):
        codes = list(ev["products"])
    products = (
        list(session.execute(select(Product.id).where(Product.code.in_(codes))).scalars())
        if codes is not None
        else None
    )
    dishes = (
        list(session.execute(select(MenuItem.id).where(MenuItem.code == ev["menu_item"])).scalars())
        if isinstance(ev.get("menu_item"), str)
        else None
    )
    start, end = f.period_from or f.found_on, f.period_to or f.found_on
    scope = _Scope(f.restaurant_id, start, end, products, dishes)
    module = f.module
    if module == "M3":
        return scope, {"receipts"}
    if module in ("M2",) or (module == "M7" and dishes is not None):
        return scope, {"sales"}
    if module == "M5":
        return scope, {"write_offs"}
    if module == "M6":
        scope.date_from = end - timedelta(days=28)
        return scope, {"receipts", "counts"}
    if module == "M4":
        if kind == "pre_count":
            return scope, {"write_offs"}
        return scope, {"counts"}
    if module == "M7" and kind == "gap":
        last = date.fromisoformat(ev["last"]) if ev.get("last") else end
        scope.date_from, scope.date_to = last - timedelta(days=GAP_LOOKBACK_DAYS), last
        return scope, {ev.get("source", "receipts")}
    # M1 and the books going below zero: every movement of the product.
    return scope, {"counts", "receipts", "write_offs", "transfers"}


def _filtered[S: "Select[*tuple[Any, ...]]"](stmt: S, model: Any, scope: _Scope, by: str) -> S:
    stmt = stmt.where(model.day >= scope.date_from, model.day <= scope.date_to)
    if scope.restaurant_id is not None:
        stmt = stmt.where(model.restaurant_id == scope.restaurant_id)
    if by == "product" and scope.products is not None:
        stmt = stmt.where(model.product_id.in_(scope.products))
    if by == "dish" and scope.dishes is not None:
        stmt = stmt.where(model.menu_item_id.in_(scope.dishes))
    return stmt


def _file(b: ImportBatch | None) -> dict[str, Any]:
    """The file a row came from; another restaurant's file (an incoming transfer) is not shown."""
    if b is None:
        return {"file": None, "file_id": None, "loaded_on": None}
    return {"file": b.filename, "file_id": str(b.id), "loaded_on": b.created_at.date().isoformat()}


def _count(session: Session, model: Any, scope: _Scope, by: str) -> int:
    counted: int = session.execute(
        _filtered(select(func.count()).select_from(model), model, scope, by)
    ).scalar_one()
    return counted


def _receipts(session: Session, scope: _Scope) -> Group:
    q = (
        select(Receipt, Product, Supplier, Restaurant, ImportBatch)
        .join(Product, Product.id == Receipt.product_id)
        .outerjoin(Supplier, Supplier.id == Receipt.supplier_id)
        .join(Restaurant, Restaurant.id == Receipt.restaurant_id)
        .join(ImportBatch, ImportBatch.id == Receipt.import_batch_id)
        .order_by(Receipt.day, Receipt.doc_no)
        .limit(LIMIT)
    )
    rows = [
        {
            "day": r.day.isoformat(),
            "doc_no": r.doc_no or "—",
            "supplier": s.name if s else "—",
            "product": p.name,
            "restaurant": place.name,
            "qty": r.qty,
            "unit": UNIT_TITLES.get(p.base_unit, p.base_unit),
            "price": (r.amount / r.qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if r.qty else None,
            "amount": r.amount,
            **_file(b),
        }
        for r, p, s, place, b in session.execute(_filtered(q, Receipt, scope, "product"))
    ]
    return Group(
        "receipts",
        "Накладные поставщиков",
        [
            Column("day", "Дата", "date"),
            Column("doc_no", "Накладная", "text"),
            Column("supplier", "Поставщик", "text"),
            Column("product", "Товар", "text"),
            Column("restaurant", "Ресторан", "text"),
            Column("qty", "Количество", "qty"),
            Column("price", "Цена за ед.", "money"),
            Column("amount", "Сумма", "money"),
        ],
        rows,
        _count(session, Receipt, scope, "product"),
    )


def _counts(session: Session, scope: _Scope) -> Group:
    # The opening count of the period is the day before it starts.
    scope = _Scope(
        scope.restaurant_id, scope.date_from - timedelta(days=1), scope.date_to, scope.products, scope.dishes
    )
    q = (
        select(InventoryCount, Product, Restaurant, ImportBatch)
        .join(Product, Product.id == InventoryCount.product_id)
        .join(Restaurant, Restaurant.id == InventoryCount.restaurant_id)
        .join(ImportBatch, ImportBatch.id == InventoryCount.import_batch_id)
        .order_by(InventoryCount.day, Product.name)
        .limit(LIMIT)
    )
    rows = [
        {
            "day": c.day.isoformat(),
            "product": p.name,
            "restaurant": place.name,
            "book": c.book_qty,
            "actual": c.actual_qty,
            "difference": (c.actual_qty - c.book_qty) if c.book_qty is not None else None,
            "unit": UNIT_TITLES.get(p.base_unit, p.base_unit),
            **_file(b),
        }
        for c, p, place, b in session.execute(_filtered(q, InventoryCount, scope, "product"))
    ]
    return Group(
        "counts",
        "Инвентаризации",
        [
            Column("day", "Дата", "date"),
            Column("product", "Товар", "text"),
            Column("restaurant", "Ресторан", "text"),
            Column("book", "По учету", "qty"),
            Column("actual", "Фактически", "qty"),
            Column("difference", "Разница", "qty"),
        ],
        rows,
        _count(session, InventoryCount, scope, "product"),
    )


def _write_offs(session: Session, scope: _Scope) -> Group:
    q = (
        select(WriteOff, Product, Restaurant, ImportBatch)
        .join(Product, Product.id == WriteOff.product_id)
        .join(Restaurant, Restaurant.id == WriteOff.restaurant_id)
        .join(ImportBatch, ImportBatch.id == WriteOff.import_batch_id)
        .order_by(WriteOff.day, Product.name)
        .limit(LIMIT)
    )
    rows = [
        {
            "day": w.day.isoformat(),
            "product": p.name,
            "restaurant": place.name,
            "qty": w.qty,
            "unit": UNIT_TITLES.get(p.base_unit, p.base_unit),
            "reason": w.reason or "—",
            **_file(b),
        }
        for w, p, place, b in session.execute(_filtered(q, WriteOff, scope, "product"))
    ]
    return Group(
        "write_offs",
        "Акты списания",
        [
            Column("day", "Дата", "date"),
            Column("product", "Товар", "text"),
            Column("restaurant", "Ресторан", "text"),
            Column("qty", "Количество", "qty"),
            Column("reason", "Причина в акте", "text"),
        ],
        rows,
        _count(session, WriteOff, scope, "product"),
    )


def _transfers(session: Session, scope: _Scope) -> Group:
    names = dict(session.execute(select(Restaurant.id, Restaurant.name)).tuples().all())
    where = [Transfer.day >= scope.date_from, Transfer.day <= scope.date_to]
    if scope.products is not None:
        where.append(Transfer.product_id.in_(scope.products))
    if scope.restaurant_id is not None:  # out of the restaurant or into it
        where.append(
            (Transfer.restaurant_id == scope.restaurant_id)
            | (Transfer.to_restaurant_id == scope.restaurant_id)
        )
    # An incoming transfer's file belongs to the sender, whom a director does not see: the row stays, no file.
    q = (
        select(Transfer, Product, ImportBatch)
        .join(Product, Product.id == Transfer.product_id)
        .outerjoin(ImportBatch, ImportBatch.id == Transfer.import_batch_id)
        .where(*where)
        .order_by(Transfer.day)
        .limit(LIMIT)
    )
    rows = [
        {
            "day": t.day.isoformat(),
            "product": p.name,
            # Another restaurant the caller does not see is named only as «другой ресторан сети».
            "route": f"{names.get(t.restaurant_id, 'другой ресторан сети')} → "
            f"{names.get(t.to_restaurant_id, 'другой ресторан сети')}",
            "qty": t.qty,
            "unit": UNIT_TITLES.get(p.base_unit, p.base_unit),
            **_file(b),
        }
        for t, p, b in session.execute(q)
    ]
    total: int = session.execute(select(func.count()).select_from(Transfer).where(*where)).scalar_one()
    return Group(
        "transfers",
        "Перемещения",
        [
            Column("day", "Дата", "date"),
            Column("product", "Товар", "text"),
            Column("route", "Откуда → куда", "text"),
            Column("qty", "Количество", "qty"),
        ],
        rows,
        total,
    )


def _sales(session: Session, scope: _Scope) -> Group:
    """Sales by day and restaurant: a receipt-level export would be thousands of lines. Grouped by ids, so two
    dishes or restaurants with one name stay apart."""
    places = dict(session.execute(select(Restaurant.id, Restaurant.name)).tuples().all())
    dishes = dict(session.execute(select(MenuItem.id, MenuItem.name)).tuples().all())
    base = (
        select(
            Sale.day,
            Sale.restaurant_id,
            Sale.menu_item_id,
            func.sum(Sale.qty),
            func.sum(Sale.revenue),
            func.min(ImportBatch.filename),
        )
        .join(ImportBatch, ImportBatch.id == Sale.import_batch_id)
        .group_by(Sale.day, Sale.restaurant_id, Sale.menu_item_id)
    )
    filtered = _filtered(base, Sale, scope, "dish")
    total: int = session.execute(select(func.count()).select_from(filtered.subquery())).scalar_one()
    rows = [
        {
            "day": d.isoformat(),
            "restaurant": places.get(place, "—"),
            "dish": dishes.get(dish, "—"),
            "qty": qty,
            "revenue": revenue,
            "file": file,
        }
        for d, place, dish, qty, revenue, file in session.execute(
            filtered.order_by(Sale.day, Sale.restaurant_id).limit(LIMIT)
        )
    ]
    return Group(
        "sales",
        "Продажи по дням",
        [
            Column("day", "Дата", "date"),
            Column("restaurant", "Ресторан", "text"),
            Column("dish", "Блюдо", "text"),
            Column("qty", "Порций", "qty"),
            Column("revenue", "Выручка", "money"),
        ],
        rows,
        total,
    )


BUILDERS = {
    "receipts": _receipts,
    "counts": _counts,
    "write_offs": _write_offs,
    "transfers": _transfers,
    "sales": _sales,
}
ORDER: Sequence[str] = ("receipts", "counts", "write_offs", "transfers", "sales")


SHAREABLE = ("product", "restaurant", "supplier", "dish")


def _fold(g: Group) -> Group:
    """A column with one value on every row (one product, one restaurant) is said once above the table."""
    for key in SHAREABLE:
        values = {r.get(key) for r in g.rows}
        if len(g.rows) > 1 and len(values) == 1 and key in {c.key for c in g.columns}:
            g.columns = [c for c in g.columns if c.key != key]
            g.same.append(str(values.pop()))
    return g


def sources(session: Session, finding_id: UUID, *, today: date) -> Sources:
    fw = service.get_finding(session, finding_id, today=today)  # the card's access rules
    scope, kinds = _scope(session, fw.finding)
    groups = [BUILDERS[k](session, scope) for k in ORDER if k in kinds]
    groups = [_fold(g) for g in groups if g.total]
    where = "по всем ресторанам сети" if scope.restaurant_id is None else "по ресторану"
    note = (
        f"Строки загруженных файлов {where} за {scope.date_from:%d.%m}–{scope.date_to:%d.%m}"
        if groups
        else "Документов нет: находка о том, чего в данных не было (пропущенная выгрузка или инвентаризация)"
    )
    return Sources(note, groups)
