from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class Role(StrEnum):
    HQ_ADMIN = "hq_admin"
    HQ_ANALYST = "hq_analyst"
    RESTAURANT_DIRECTOR = "restaurant_director"

    @property
    def is_hq(self) -> bool:
        return self in (Role.HQ_ADMIN, Role.HQ_ANALYST)


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))


class Restaurant(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "restaurants"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    format: Mapped[str | None] = mapped_column(String(100))
    opened_on: Mapped[date | None] = mapped_column(Date)


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email_lower", func.lower(text("email")), unique=True),)

    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class RoleAssignment(IdMixin, TenantMixin, TimestampMixin, Base):
    """A role with its scope: HQ roles cover the whole tenant, a director covers exactly one restaurant."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('hq_admin', 'hq_analyst', 'restaurant_director')",
            name="role_valid",
        ),
        CheckConstraint(
            "(role = 'restaurant_director') = (restaurant_id IS NOT NULL)",
            name="scope_matches_role",
        ),
        Index("uq_role_assignments_one_per_user", "user_id", unique=True),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(50))
    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))


class AuditLog(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
