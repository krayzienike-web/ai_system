"""Operational facts of a restaurant. Every row knows the import batch it came from (invariant 6)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin

QTY = Numeric(14, 4)
MONEY = Numeric(14, 2)


class _Fact(IdMixin, TenantMixin):
    restaurant_id: Mapped[UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    import_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)


class Sale(_Fact, Base):
    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_restaurant_day", "restaurant_id", "day"),
        CheckConstraint("qty >= 0", name="qty_nonnegative"),
    )

    menu_item_id: Mapped[UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    revenue: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))


class Receipt(_Fact, Base):
    """A line of a supplier invoice. Quantity is in the product's base unit."""

    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_restaurant_day", "restaurant_id", "day"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )

    doc_no: Mapped[str | None] = mapped_column(String(100))
    supplier_id: Mapped[UUID | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    vat: Mapped[Decimal | None] = mapped_column(MONEY)


class WriteOff(_Fact, Base):
    __tablename__ = "write_offs"
    __table_args__ = (
        Index("ix_write_offs_restaurant_day", "restaurant_id", "day"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    reason: Mapped[str | None] = mapped_column(String(200))


class InventoryCount(_Fact, Base):
    """A line of a stock count: what the books said and what was actually counted."""

    __tablename__ = "inventory_counts"
    __table_args__ = (
        Index("ix_inventory_counts_restaurant_day", "restaurant_id", "day"),
        CheckConstraint("actual_qty >= 0", name="actual_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    book_qty: Mapped[Decimal | None] = mapped_column(QTY)
    actual_qty: Mapped[Decimal] = mapped_column(QTY)
