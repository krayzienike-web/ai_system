"""№ 3. A claim or a request to a supplier about prices (docs/07 «ИИ-агенты», ADR 0010; stage 10).

For a confirmed open M3 finding about a supplier's price — money is asked of a supplier only on a finding the
HQ has checked:
- «Цена выше договорной» (`contract`): a claim — every invoice above the agreed price, with its overpayment,
  and the total to return;
- «Скачок цены» (`jump`, a restaurant) and «Рост цены по сети» (`growth`): a request to justify the rise —
  the price before and after, the invoices since, what the rise has cost so far.
The invoices are the receipts of the finding's period, read again from the data: the note lists what a
supplier can check, by number and date. The clause of the contract is a blank to fill: contracts are not in
the system. The HQ sends it — «Отправлено» records that, nothing goes out by itself.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.catalog.models import Product, Supplier
from app.insights.models import Finding, FindingStatus
from app.operations.models import Receipt
from app.tenancy.models import Restaurant

KINDS = ("contract", "jump", "growth")
OPEN = (FindingStatus.NEW, FindingStatus.IN_WORK, FindingStatus.IN_EXPERIMENT)
MAX_INVOICES = 12  # in the list; the total counts them all


def _kopecks(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty(value: Decimal) -> str:
    return plain(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _invoices(
    session: Session, f: Finding, product: Product, supplier: Supplier, since: date, codes: dict[Any, str]
) -> list[Receipt]:
    q = select(Receipt).where(
        Receipt.product_id == product.id,
        Receipt.supplier_id == supplier.id,
        Receipt.day >= since,
        Receipt.day <= f.period_to,
        Receipt.qty > 0,
    )
    if f.restaurant_id is not None:
        q = q.where(Receipt.restaurant_id == f.restaurant_id)
    rows = list(session.execute(q).scalars())
    return sorted(rows, key=lambda r: (r.day, codes.get(r.restaurant_id, ""), r.doc_no or ""))


def _draft(session: Session, f: Finding, codes: dict[Any, str]) -> NoteDraft | None:
    ev = f.evidence or {}
    kind = ev.get("kind")
    product = session.execute(select(Product).where(Product.code == ev.get("product"))).scalar_one_or_none()
    supplier = session.execute(select(Supplier).where(Supplier.name == ev.get("supplier"))).scalars().first()
    if (
        kind not in KINDS
        or product is None
        or supplier is None
        or f.period_from is None
        or f.period_to is None
    ):
        return None
    if kind == "contract":
        reference = Decimal(ev["contract_price"])
        since = f.period_from
    else:
        reference = Decimal(ev["price_before"])
        since = date.fromisoformat(ev["since"])
    lines = []
    for r in _invoices(session, f, product, supplier, since, codes):
        price = r.amount / r.qty
        extra = r.amount - reference * r.qty
        if extra <= 0:  # at or below the reference: nothing to ask about
            continue
        lines.append(
            {
                "doc": r.doc_no or "",
                "day": r.day.isoformat(),
                "restaurant": codes.get(r.restaurant_id, ""),
                "qty": _qty(r.qty),
                "price": _kopecks(price),
                "amount": _kopecks(r.amount),
                "extra": _kopecks(extra),
            }
        )
    if not lines:
        return None
    total = sum((Decimal(x["extra"]) for x in lines), Decimal(0))
    qty = sum((Decimal(x["qty"]) for x in lines), Decimal(0))
    paid = sum((Decimal(x["amount"]) for x in lines), Decimal(0))
    by_restaurant: dict[str, Decimal] = defaultdict(Decimal)
    for x in lines:
        by_restaurant[x["restaurant"]] += Decimal(x["extra"])
    return NoteDraft(
        agent=Agent.SUPPLIER_CLAIM,
        audience=Audience.HQ,
        restaurant_id=f.restaurant_id,
        key=f"supplier_claim:{f.key}",
        for_date=f.period_to,
        facts={
            "kind": kind,
            "finding": f.title,
            "supplier": supplier.name,
            "product": product.name,
            "unit": product.base_unit,
            "reference": _kopecks(reference),  # the contract price, or the price before the rise
            "price": _kopecks(paid / qty),  # what the listed invoices cost on average
            "since": since.isoformat(),
            "until": f.period_to.isoformat(),
            "invoices": lines[:MAX_INVOICES],
            "invoices_total": len(lines),
            "restaurants": len(by_restaurant),
            "extra": _kopecks(total),
            "growth_pct": str(((paid / qty / reference - 1) * 100).quantize(Decimal("0.1"))),
        },
        proposal={"action": "claim"},
    )


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    codes = {r.id: r.name for r in restaurants}  # the invoices name their restaurant
    found = session.execute(
        select(Finding)
        .where(Finding.module == "M3", Finding.status.in_(OPEN), Finding.key.is_not(None))
        .order_by(Finding.key)
    ).scalars()
    out = []
    for f in found:
        if f.checked and (d := _draft(session, f, codes)) is not None:
            out.append(d)
    return out
