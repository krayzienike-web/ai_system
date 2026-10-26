from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class BatchStatus(StrEnum):
    FAILED = "failed"  # blocking errors: nothing can be published
    NEEDS_MATCHING = "needs_matching"  # the file is fine, but some names must be matched to the catalog once
    VALIDATED = "validated"  # ready to publish (warnings allowed)
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"


class ImportBatch(IdMixin, TenantMixin, TimestampMixin, Base):
    """One uploaded file: the raw bytes, the validation report and what happened to it.

    A batch without a restaurant holds network reference data and is visible to HQ only (RLS).
    """

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('failed', 'validated', 'published', 'rolled_back')", name="status_valid"),
        Index("ix_import_batches_tenant_sha", "tenant_id", "sha256"),
    )

    restaurant_id: Mapped[UUID | None] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    template: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    # MVP keeps the original file in the database; object storage comes with real volumes.
    raw: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20))
    rows_total: Mapped[int] = mapped_column(default=0)
    rows_valid: Mapped[int] = mapped_column(default=0)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Names the catalog does not know yet, with suggestions: [{kind, code, name, rows, candidates}].
    unmatched: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # "kind:source_key" of the remembered matches this file relied on when it was published.
    aliases_used: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    column_map: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
