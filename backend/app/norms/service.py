"""Norms of the network: what counts as a problem. Reads fall back to defaults; HQ admins change them."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import MenuItem, Product
from app.core.errors import ForbiddenError, InvalidError
from app.imports.matching import normalize
from app.norms import defaults
from app.norms.models import NormSettings
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

REASON_KINDS = ("loss", "planned", "shortage")


@dataclass(frozen=True)
class Reason:
    code: str
    title: str
    kind: str
    synonyms: tuple[str, ...]


@dataclass
class Norms:
    food_cost_target_pct: Decimal = defaults.FOOD_COST_TARGET_PCT
    food_cost_by_category: dict[str, Decimal] = field(default_factory=dict)
    loss_default_pct: Decimal = defaults.LOSS_DEFAULT_PCT
    loss_by_category: dict[str, Decimal] = field(default_factory=lambda: dict(defaults.LOSS_BY_CATEGORY_PCT))
    reasons: list[Reason] = field(
        default_factory=lambda: [Reason(c, t, k, tuple(s)) for c, t, k, s in defaults.WRITE_OFF_REASONS]
    )
    review_findings: bool = True  # engine findings wait for a manual check before directors see them

    def food_cost_target(self, menu_category: str | None) -> Decimal:
        return self.food_cost_by_category.get(menu_category or "", self.food_cost_target_pct)

    def loss_allowance(self, product_category: str | None) -> Decimal:
        return self.loss_by_category.get(product_category or "", self.loss_default_pct)

    def classify(self, reason_text: str | None) -> str:
        """The network's reason for a write-off line of an export; unknown → «other»."""
        text = normalize(reason_text or "")
        if not text:
            return "other"
        for reason in self.reasons:
            if normalize(reason.title) == text or any(normalize(s) in text for s in reason.synonyms if s):
                return reason.code
        return "other"


def load_norms(session: Session) -> Norms:
    row = session.execute(select(NormSettings)).scalar_one_or_none()
    if row is None:
        return Norms()
    return Norms(
        food_cost_target_pct=row.food_cost_target_pct,
        food_cost_by_category={k: Decimal(v) for k, v in row.food_cost_by_category.items()},
        loss_default_pct=row.loss_default_pct,
        loss_by_category={k: Decimal(v) for k, v in row.loss_by_category.items()},
        reasons=[
            Reason(r["code"], r["title"], r["kind"], tuple(r["synonyms"])) for r in row.write_off_reasons
        ]
        or Norms().reasons,
        review_findings=row.review_findings,
    )


def _pct(value: Any, low: Decimal, high: Decimal, what: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception:
        raise InvalidError(f"{what}: нужно число") from None
    if not low <= number <= high:
        raise InvalidError(f"{what}: от {low} до {high}%")
    return number.quantize(Decimal("0.01"))


def save_norms(session: Session, ctx: AccessContext, body: dict[str, Any]) -> Norms:
    if not ctx.can(Permission.NORMS_MANAGE):
        raise ForbiddenError("Нормы меняет администратор управляющей компании")
    food = _pct(body["food_cost_target_pct"], Decimal(5), Decimal(80), "Целевой фудкост")
    food_by = {
        str(k).strip(): _pct(v, Decimal(5), Decimal(80), f"Фудкост «{k}»")
        for k, v in body.get("food_cost_by_category", {}).items()
        if str(k).strip()
    }
    loss = _pct(body["loss_default_pct"], Decimal(0), Decimal(30), "Допустимые потери")
    loss_by = {
        str(k).strip(): _pct(v, Decimal(0), Decimal(30), f"Потери «{k}»")
        for k, v in body.get("loss_by_category", {}).items()
        if str(k).strip()
    }
    reasons = []
    seen: set[str] = set()
    for r in body.get("write_off_reasons", []):
        code, title, kind = str(r["code"]).strip(), str(r["title"]).strip(), r["kind"]
        if not code or not title or code in seen:
            raise InvalidError("У каждой причины списания нужны свой код и название")
        if kind not in REASON_KINDS:
            raise InvalidError(f"Причина «{title}»: вид — потеря, плановый расход или закрытие недостачи")
        seen.add(code)
        synonyms = [s.strip() for s in r.get("synonyms", []) if s.strip()]
        reasons.append({"code": code, "title": title, "kind": kind, "synonyms": synonyms})
    if "other" not in seen:
        reasons.append({"code": "other", "title": "Прочее", "kind": "loss", "synonyms": []})

    row = session.execute(select(NormSettings)).scalar_one_or_none()
    if row is None:
        row = NormSettings(tenant_id=ctx.tenant_id)
        session.add(row)
    row.food_cost_target_pct = food
    row.food_cost_by_category = {k: str(v) for k, v in food_by.items()}
    row.loss_default_pct = loss
    row.loss_by_category = {k: str(v) for k, v in loss_by.items()}
    row.write_off_reasons = reasons
    row.review_findings = bool(body.get("review_findings", True))
    row.updated_by = str(ctx.user_id)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="norms.save",
        entity="norm_settings",
        entity_id=row.id,
    )
    return load_norms(session)


def categories(session: Session) -> tuple[list[str], list[str]]:
    """Categories that exist in the catalog: menu (for food cost) and products (for losses)."""
    menu = session.execute(
        select(func.distinct(MenuItem.category)).where(MenuItem.category.is_not(None))
    ).scalars()
    products = session.execute(
        select(func.distinct(Product.category)).where(Product.category.is_not(None))
    ).scalars()
    return sorted(c for c in menu if c), sorted(c for c in products if c)
