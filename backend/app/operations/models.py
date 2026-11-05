"""Operational facts of a restaurant. Every row knows the import batch it came from (invariant 6)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Numeric, String
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
        Index("ix_sales_tenant_day", "tenant_id", "day"),
        CheckConstraint("qty >= 0", name="qty_nonnegative"),
    )

    menu_item_id: Mapped[UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    revenue: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    cashier: Mapped[str | None] = mapped_column(String(100))  # stage 6.5: discounts by cashier


class Receipt(_Fact, Base):
    """A line of a supplier invoice. Quantity is in the product's base unit."""

    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_restaurant_day", "restaurant_id", "day"),
        Index("ix_receipts_tenant_day", "tenant_id", "day"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )

    doc_no: Mapped[str | None] = mapped_column(String(100))
    supplier_id: Mapped[UUID | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    vat: Mapped[Decimal | None] = mapped_column(MONEY)


class Transfer(_Fact, Base):
    """Goods moved between restaurants of the network. Stored once, from the sender's export
    (`restaurant_id` is the sender); the receiver reads its incoming rows (row-level security)."""

    __tablename__ = "transfers"
    __table_args__ = (
        Index("ix_transfers_restaurant_day", "restaurant_id", "day"),
        Index("ix_transfers_tenant_day", "tenant_id", "day"),
        Index("ix_transfers_to_day", "to_restaurant_id", "day"),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("to_restaurant_id <> restaurant_id", name="not_to_itself"),
    )

    to_restaurant_id: Mapped[UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)


class WriteOff(_Fact, Base):
    __tablename__ = "write_offs"
    __table_args__ = (
        Index("ix_write_offs_restaurant_day", "restaurant_id", "day"),
        Index("ix_write_offs_tenant_day", "tenant_id", "day"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    reason: Mapped[str | None] = mapped_column(String(200))  # as in the export
    reason_code: Mapped[str] = mapped_column(String(50), default="other", server_default="other")


class InventoryCount(_Fact, Base):
    """A line of a stock count: what the books said and what was actually counted."""

    __tablename__ = "inventory_counts"
    __table_args__ = (
        Index("ix_inventory_counts_restaurant_day", "restaurant_id", "day"),
        Index("ix_inventory_counts_tenant_day", "tenant_id", "day"),
        CheckConstraint("actual_qty >= 0", name="actual_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    book_qty: Mapped[Decimal | None] = mapped_column(QTY)
    actual_qty: Mapped[Decimal] = mapped_column(QTY)


class StockBalance(_Fact, Base):
    """«Остатки на дату» (iiko, stage 6.5): the books' stock of a product at the end of a day. Between counts
    it says what lies on the shelves — for overstock (M6) and a closer stock-out forecast."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        Index("ix_stock_balances_restaurant_day", "restaurant_id", "day"),
        Index("ix_stock_balances_tenant_day", "tenant_id", "day"),
        CheckConstraint("qty >= 0", name="qty_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY)


class Void(_Fact, Base):
    """«Удаления и отмены» (r_keeper, stage 6.5): a dish removed from a check or a check cancelled — by whom,
    before or after the check was printed. Many after printing are a risk of abuse at the till."""

    __tablename__ = "voids"
    __table_args__ = (
        Index("ix_voids_restaurant_day", "restaurant_id", "day"),
        Index("ix_voids_tenant_day", "tenant_id", "day"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
    )

    check_no: Mapped[str | None] = mapped_column(String(100))
    menu_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(1))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    cashier: Mapped[str | None] = mapped_column(String(100))
    after_print: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(200))
