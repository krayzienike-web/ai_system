"""Engine parameters of the network: shown and edited in the units people use (75 %, 3 000 ₽), stored in
the units the engine uses (0.75, 3000). Only HQ admins change them; every role that sees findings
may read them."""

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import params
from app.core.errors import ForbiddenError, InvalidError
from app.norms.models import NormSettings
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission


def describe(session: Session) -> list[dict[str, Any]]:
    current = params.load(session)
    return [
        {
            "key": d.key,
            "module": d.module,
            "title": d.title,
            "unit": d.unit,
            "meaning": d.meaning,
            "low": d.low,
            "high": d.high,
            "value": d.shown(getattr(current, d.key)),
            "default": d.shown(getattr(params.DEFAULT, d.key)),
        }
        for d in params.DEFS
    ]


def save(session: Session, ctx: AccessContext, values: dict[str, Any]) -> list[dict[str, Any]]:
    """`values`: key → number in shown units, or None to return to the default."""
    if not ctx.can(Permission.NORMS_MANAGE):
        raise ForbiddenError("Параметры движка меняет администратор управляющей компании")
    row = session.execute(select(NormSettings)).scalar_one_or_none()
    if row is None:
        # Norms are created on first save with defaults; engine parameters may come first.
        from app.norms import defaults

        row = NormSettings(
            tenant_id=ctx.tenant_id,
            food_cost_target_pct=defaults.FOOD_COST_TARGET_PCT,
            loss_default_pct=defaults.LOSS_DEFAULT_PCT,
            loss_by_category={k: str(v) for k, v in defaults.LOSS_BY_CATEGORY_PCT.items()},
        )
        session.add(row)
    stored = dict(row.engine_params or {})
    for key, raw in values.items():
        d = params.BY_KEY.get(key)
        if d is None:
            raise InvalidError(f"Неизвестный параметр «{key}»")
        if raw is None:
            stored.pop(key, None)
            continue
        try:
            shown = Decimal(str(raw).replace(",", "."))
        except InvalidOperation:
            raise InvalidError(f"«{d.title}»: нужно число") from None
        if not d.low <= shown <= d.high:
            raise InvalidError(f"«{d.title}»: от {d.shown(d.low / d.scale)} до {d.shown(d.high / d.scale)}")
        value = d.stored(shown)
        if isinstance(value, int) and Decimal(value) != shown / d.scale:
            raise InvalidError(f"«{d.title}»: нужно целое число")
        stored[key] = str(value)
    row.engine_params = stored
    session.flush()
    audit(session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, action="engine_params.save", payload=stored)
    return describe(session)
