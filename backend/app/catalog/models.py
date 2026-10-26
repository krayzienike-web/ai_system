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
    # A semi-finished product (соус, тесто) has its own recipe per 1 base unit.
    is_semi: Mapped[bool] = mapped_column(default=False, server_default="false")


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
    """One ingredient of a recipe (ТТК), gross quantity in the product's base unit.

    The recipe belongs to a menu item (per portion) or to a semi-finished product (per 1 base unit).
    A recipe version is the set of lines with the same valid_from; history is never rewritten (invariant 2).
    """

    __tablename__ = "recipe_lines"
    __table_args__ = (
        CheckConstraint("gross_qty > 0", name="gross_positive"),
        CheckConstraint("(menu_item_id IS NULL) <> (semi_product_id IS NULL)", name="one_parent"),
    )

    menu_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("menu_items.id", ondelete="CASCADE"), index=True
    )
    semi_product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    gross_qty: Mapped[Decimal] = mapped_column(QTY)
    valid_from: Mapped[date] = mapped_column(Date)


class AliasKind(StrEnum):
    PRODUCT = "product"
    MENU_ITEM = "menu_item"
    SUPPLIER = "supplier"


class NameAlias(IdMixin, TenantMixin, TimestampMixin, Base):
    """A confirmed match: how a product (dish, supplier) is called in another system's export.

    Network-wide when set by HQ; a director's match applies only to their restaurant, so one restaurant's
    choice never changes another restaurant's numbers.
    """

    __tablename__ = "name_aliases"
    __table_args__ = (CheckConstraint("kind IN ('product', 'menu_item', 'supplier')", name="kind_valid"),)

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    # Normalised source name, or "code:<code>" when the file has a code we do not know.
    source_key: Mapped[str] = mapped_column(String(300))
    source_text: Mapped[str] = mapped_column(String(300))
    target_id: Mapped[UUID]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
