"""What the code knows around a finding: the facts the assistant's hypotheses are built on (ADR 0008).

Gathered for the finding's own restaurant only (or for the network, for a network finding), whoever asks:
the hypotheses are kept and a director may read them later, so they never hold another restaurant's rows or
name (code review 27.10.2026, p. 10). Figures are computed here and formatted like the tools'; the model
only reads them, and every number of its proposal is checked against this context.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.tools import day, money, pct, price
from app.catalog.models import MenuItem, Product, Supplier
from app.core import words
from app.experiments.models import Experiment
from app.insights.models import Finding
from app.insights.visible import VisibleFinding, visible_finding
from app.norms.models import NormSettings
from app.operations.models import InventoryCount, Receipt, WriteOff
from app.overview.service import PROCESS_TITLE
from app.tenancy.context import AccessContext

LOOKBACK_DAYS = 120  # how far back «what changed around» looks


def subject_of_key(module: str | None, key: str | None) -> tuple[str | None, str | None]:
    """(product code, menu item code) a finding is about, from its engine key («M1:R01:P01», «M2:net:M07»)."""
    parts = (key or "").split(":")
    if len(parts) < 3 or not parts[2][:1].isupper() or not parts[2][1:2].isdigit():
        return None, None  # «M4:R01:pre-count»: about the restaurant, not an item
    code = parts[2].split("-")[0]
    return (None, code) if module in ("M2", "M7") and code.startswith("M") else (code, None)


def subject(finding: VisibleFinding, key: str | None) -> tuple[str | None, str | None]:
    return subject_of_key(finding.module, key)


def _suppliers(
    session: Session, product_id: UUID, restaurant_id: UUID | None, since: date
) -> list[dict[str, Any]]:
    """Who sold the product and at what price, month by month: a change of supplier or price shows here."""
    month = func.date_trunc("month", Receipt.day)
    query = (
        select(month, Supplier.name, func.sum(Receipt.amount), func.sum(Receipt.qty))
        .outerjoin(Supplier, Supplier.id == Receipt.supplier_id)
        .where(Receipt.product_id == product_id, Receipt.day >= since)
        .group_by(month, Supplier.name)
        .order_by(month, Supplier.name)
    )
    if restaurant_id is not None:
        query = query.where(Receipt.restaurant_id == restaurant_id)
    return [
        {
            "month": f"{m:%m.%Y}",
            "supplier": s or "не указан",
            "avg_price": price(a / q),
            "bought": words.number(q, 1),
        }
        for m, s, a, q in session.execute(query)
    ]


def _write_off_reasons(
    session: Session, product_id: UUID, restaurant_id: UUID | None, since: date, until: date
) -> list[dict[str, Any]]:
    query = (
        select(WriteOff.reason, func.sum(WriteOff.qty))
        .where(WriteOff.product_id == product_id, WriteOff.day >= since, WriteOff.day <= until)
        .group_by(WriteOff.reason)
    )
    if restaurant_id is not None:
        query = query.where(WriteOff.restaurant_id == restaurant_id)
    rows = list(session.execute(query))
    total = sum((q for _, q in rows), Decimal(0))
    return [
        {"reason": r or "не указана", "share": pct(q / total) if total else None}
        for r, q in sorted(rows, key=lambda x: -x[1])
    ]


def _count_days(session: Session, restaurant_id: UUID, since: date) -> list[str]:
    days = session.execute(
        select(InventoryCount.day)
        .where(InventoryCount.restaurant_id == restaurant_id, InventoryCount.day >= since)
        .distinct()
        .order_by(InventoryCount.day)
    ).scalars()
    return [d for d in (day(x) for x in days) if d]


def _data_problems(session: Session, restaurant_id: UUID, finding_id: UUID) -> list[str]:
    """Open data-quality findings (M7) of the same restaurant: a figure may be wrong because the data is."""
    return list(
        session.execute(
            select(Finding.title).where(
                Finding.restaurant_id == restaurant_id,
                Finding.module == "M7",
                Finding.status != "dismissed",
                Finding.id != finding_id,
            )
        ).scalars()
    )


def _checks_of_similar(session: Session, finding: VisibleFinding) -> list[dict[str, Any]]:
    """Checks of changes made for findings of the same kind before, anywhere in the network, without names:
    what worked and what did not."""
    rows = session.execute(
        select(Experiment)
        .join(Finding, Finding.id == Experiment.finding_id)
        .where(Finding.module == finding.module, Finding.id != finding.id, Experiment.status == "completed")
        .order_by(Experiment.completed_on.desc())
        .limit(5)
    ).scalars()
    out = []
    for c in rows:
        # The words of a check in another restaurant may name it: then only its outcome is told.
        here = finding.restaurant_id is None or finding.restaurant_id in c.test_restaurant_ids
        out.append(
            {
                "check": c.title if here else "проверка в другом ресторане сети",
                "verdict": c.verdict,
                "effect_per_month": money(c.effect_rub_month),
                "result": c.result_text if here else None,
            }
        )
    return out


def build(session: Session, ctx: AccessContext, finding_id: UUID, today: date) -> dict[str, Any]:
    """The context of one finding the caller may see (else NotFoundError, as on the card)."""
    f = visible_finding(session, ctx, finding_id, today=today)
    row = session.get(Finding, f.id)
    product_code, menu_code = subject(f, row.key if row else None)
    since = today - timedelta(days=LOOKBACK_DAYS)
    view = f.view or {}
    rules = session.execute(select(NormSettings.network_rules)).scalar() or []
    out: dict[str, Any] = {
        "finding": {
            "title": f.title,
            "module": f.module,
            "process": PROCESS_TITLE.get(f.process, f.process),
            "restaurant": f.restaurant_name or "вся сеть",
            "period": f"{day(f.period_from)}–{day(f.period_to)}" if f.period_from else None,
            "effect_per_month": money(f.effect_rub_month),
            "summary": view.get("summary") or f.headline,
            "metric": view.get("metric"),
            "typical_causes": view.get("causes") or [],
            "actions_by_rules": f.actions,
        },
        "network_rules": list(rules),
    }
    if product_code:
        product = session.execute(select(Product).where(Product.code == product_code)).scalar()
        if product is not None:
            out["product"] = {
                "name": product.name,
                "category": product.category,
                "shelf_life_days": product.shelf_life_days,
            }
            out["suppliers_by_month"] = _suppliers(session, product.id, f.restaurant_id, since)
            out["write_off_reasons"] = _write_off_reasons(
                session, product.id, f.restaurant_id, f.period_from or since, f.period_to or today
            )
    if menu_code:
        item = session.execute(select(MenuItem).where(MenuItem.code == menu_code)).scalar()
        if item is not None:
            out["menu_item"] = {"name": item.name, "category": item.category, "menu_price": money(item.price)}
    if f.restaurant_id is not None:
        out["inventory_count_days"] = _count_days(session, f.restaurant_id, since)
        out["data_problems"] = _data_problems(session, f.restaurant_id, f.id)
    out["checks_of_similar_findings"] = _checks_of_similar(session, f)
    facts: dict[str, Any] = _drop_empty(out)
    return facts


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_empty(v) for k, v in value.items() if v not in (None, [], {}, "")}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value
