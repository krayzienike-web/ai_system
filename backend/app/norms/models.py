from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TenantMixin, TimestampMixin


class NormSettings(IdMixin, TenantMixin, TimestampMixin, Base):
    """The network's norms, one row per tenant. Missing parts fall back to app/norms/defaults.py."""

    __tablename__ = "norm_settings"
    __table_args__ = (
        CheckConstraint("food_cost_target_pct > 0 AND food_cost_target_pct < 100", name="food_cost_range"),
        CheckConstraint("loss_default_pct >= 0 AND loss_default_pct < 100", name="loss_range"),
    )

    food_cost_target_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    # {"Пицца": "28.00", ...} — overrides by menu category
    food_cost_by_category: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    loss_default_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    loss_by_category: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # [{"code", "title", "kind", "synonyms"}]
    write_off_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    updated_by: Mapped[str | None] = mapped_column(String(64))
    # Engine findings wait for a manual check before directors see them (on while the engine is new).
    review_findings: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # The network's own engine thresholds in engine units, as strings (analytics/params.py); {} = defaults.
    engine_params: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
