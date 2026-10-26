"""Everything the engine reads, loaded once per run under the caller's row-level security."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import MenuItem, Product, RecipeLine, Supplier
from app.catalog.recipes import Line
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tenancy.models import Restaurant


@dataclass(frozen=True)
class ProductInfo:
    code: str
    name: str
    category: str | None
    unit: str
    shelf_life_days: int | None
    is_semi: bool


@dataclass(frozen=True)
class MenuInfo:
    code: str
    name: str
    category: str | None
    price: Decimal | None


@dataclass(frozen=True)
class SaleRow:
    restaurant: UUID
    day: date
    menu_item: UUID
    qty: Decimal
    revenue: Decimal


@dataclass(frozen=True)
class ReceiptRow:
    restaurant: UUID
    day: date
    product: UUID
    supplier: UUID | None
    qty: Decimal
    amount: Decimal  # as in the invoice, VAT included


@dataclass(frozen=True)
class TransferRow:
    sender: UUID
    receiver: UUID
    day: date
    product: UUID
    qty: Decimal


@dataclass(frozen=True)
class WriteOffRow:
    restaurant: UUID
    day: date
    product: UUID
    qty: Decimal
    reason_code: str


@dataclass(frozen=True)
class CountRow:
    restaurant: UUID
    day: date
    product: UUID
    book: Decimal | None
    actual: Decimal


@dataclass
class Facts:
    restaurants: dict[UUID, str] = field(default_factory=dict)  # id -> code
    products: dict[UUID, ProductInfo] = field(default_factory=dict)
    suppliers: dict[UUID, str] = field(default_factory=dict)  # id -> name
    menu: dict[UUID, MenuInfo] = field(default_factory=dict)
    recipe_lines: list[Line] = field(default_factory=list)
    sales: list[SaleRow] = field(default_factory=list)
    receipts: list[ReceiptRow] = field(default_factory=list)
    transfers: list[TransferRow] = field(default_factory=list)
    write_offs: list[WriteOffRow] = field(default_factory=list)
    counts: list[CountRow] = field(default_factory=list)


def load_facts(session: Session) -> Facts:
    f = Facts()
    f.restaurants = dict(session.execute(select(Restaurant.id, Restaurant.code)).all())
    for p in session.execute(select(Product)).scalars():
        f.products[p.id] = ProductInfo(p.code, p.name, p.category, p.base_unit, p.shelf_life_days, p.is_semi)
    f.suppliers = dict(session.execute(select(Supplier.id, Supplier.name)).all())
    for m in session.execute(select(MenuItem)).scalars():
        f.menu[m.id] = MenuInfo(m.code, m.name, m.category, m.price)
    for r in session.execute(select(RecipeLine)).scalars():
        parent = r.menu_item_id or r.semi_product_id
        assert parent is not None
        f.recipe_lines.append(Line(parent, r.product_id, r.gross_qty, r.valid_from))
    f.sales = [
        SaleRow(*row)
        for row in session.execute(
            select(Sale.restaurant_id, Sale.day, Sale.menu_item_id, Sale.qty, Sale.revenue)
        ).all()
    ]
    f.receipts = [
        ReceiptRow(*row)
        for row in session.execute(
            select(
                Receipt.restaurant_id,
                Receipt.day,
                Receipt.product_id,
                Receipt.supplier_id,
                Receipt.qty,
                Receipt.amount,
            )
        ).all()
    ]
    f.transfers = [
        TransferRow(*row)
        for row in session.execute(
            select(
                Transfer.restaurant_id,
                Transfer.to_restaurant_id,
                Transfer.day,
                Transfer.product_id,
                Transfer.qty,
            )
        ).all()
    ]
    f.write_offs = [
        WriteOffRow(*row)
        for row in session.execute(
            select(
                WriteOff.restaurant_id, WriteOff.day, WriteOff.product_id, WriteOff.qty, WriteOff.reason_code
            )
        ).all()
    ]
    f.counts = [
        CountRow(*row)
        for row in session.execute(
            select(
                InventoryCount.restaurant_id,
                InventoryCount.day,
                InventoryCount.product_id,
                InventoryCount.book_qty,
                InventoryCount.actual_qty,
            )
        ).all()
    ]
    return f
