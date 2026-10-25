"""Network reference data: products, suppliers, menu items and recipes (ТТК). Shared by the whole tenant."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin

QTY = Numeric(14, 4)
MONEY = Numeric(14, 2)


class BaseUnit(StrEnum):
    KG = "kg"
    L = "l"
    PCS = "pcs"


class Product(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("base_unit IN ('kg', 'l', 'pcs')", name="base_unit_valid"),
    )

    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(100))
    base_unit: Mapped[str] = mapped_column(String(10))
    shelf_life_days: Mapped[int | None]


class Supplier(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    inn: Mapped[str | None] = mapped_column(String(12))


class MenuItem(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal | None] = mapped_column(MONEY)


class RecipeLine(IdMixin, TenantMixin, TimestampMixin, Base):
    """One ingredient of a menu item's recipe (ТТК), gross quantity in the product's base unit.

    A recipe version is the set of lines with the same valid_from; history is never rewritten (invariant 2).
    """

    __tablename__ = "recipe_lines"
    __table_args__ = (
        UniqueConstraint("menu_item_id", "product_id", "valid_from"),
        CheckConstraint("gross_qty > 0", name="gross_positive"),
    )

    menu_item_id: Mapped[UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    gross_qty: Mapped[Decimal] = mapped_column(QTY)
    valid_from: Mapped[date] = mapped_column(Date)
