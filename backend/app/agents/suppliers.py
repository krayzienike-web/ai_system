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

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.agents.texts import plain
from app.analytics import params
from app.catalog.models import ContractPrice, Product, Supplier
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


def _supplier(session: Session, name: str | None) -> Supplier | None:
    """The finding names its supplier: only a name one supplier of the network has — two «Метро» are not
    told apart, so no letter rather than one with another supplier's invoices (backend review, p. 3)."""
    found = list(session.execute(select(Supplier).where(Supplier.name == name)).scalars()) if name else []
    return found[0] if len(found) == 1 else None


def _contract_on(contracts: list[ContractPrice], day: date) -> Decimal | None:
    """The price agreed for that day: the latest contract in force, as the engine's M3 takes it."""
    valid = [c for c in contracts if c.valid_from <= day and (c.valid_to is None or day <= c.valid_to)]
    return max(valid, key=lambda c: c.valid_from).price if valid else None


def _draft(session: Session, f: Finding, codes: dict[Any, str], tolerance: Decimal) -> NoteDraft | None:
    ev = f.evidence or {}
    kind = ev.get("kind")
    product = session.execute(select(Product).where(Product.code == ev.get("product"))).scalar_one_or_none()
    supplier = _supplier(session, ev.get("supplier"))
    if kind not in KINDS or product is None or supplier is None:
        return None
    if f.period_from is None or f.period_to is None:
        return None
    invoices = []
    if kind == "contract":
        # Each invoice against the contract in force on its day, with the engine's rounding allowance.
        contracts = list(
            session.execute(
                select(ContractPrice).where(
                    ContractPrice.supplier_id == supplier.id, ContractPrice.product_id == product.id
                )
            ).scalars()
        )
        since = f.period_from
        before = None
        for r in _invoices(session, f, product, supplier, since, codes):
            agreed = _contract_on(contracts, r.day)
            if agreed is not None:
                invoices.append((r, agreed, r.amount / r.qty > agreed * (1 + tolerance)))
    else:
        # The price before the rise, moved as the rest of the network moved (the finding's expected price).
        before = Decimal(ev["price_before"])
        expected = before * (1 + Decimal(ev.get("network_growth") or 0))
        since = date.fromisoformat(ev["since"])
        rows = _invoices(session, f, product, supplier, since, codes)
        invoices = [(r, expected, r.amount / r.qty > expected) for r in rows]
    if not invoices:
        return None
    lines = []
    for r, reference, above in invoices:
        if not above:
            continue
        lines.append(
            {
                "doc": r.doc_no or "",
                "day": r.day.isoformat(),
                "restaurant": codes.get(r.restaurant_id, ""),
                "qty": _qty(r.qty),
                "price": _kopecks(r.amount / r.qty),
                "reference": _kopecks(reference),
                "amount": _kopecks(r.amount),
                "extra": _kopecks(r.amount - reference * r.qty),
            }
        )
    if not lines:
        return None
    total = sum((Decimal(x["extra"]) for x in lines), Decimal(0))
    if before is None:
        # A claim: what the invoices above the contract cost on average, against the contract of their days.
        over = [(r, ref) for r, ref, up in invoices if up]
        price = sum((r.amount for r, _ in over), Decimal(0)) / sum((r.qty for r, _ in over), Decimal(0))
        reference, lowest = max(ref for _, ref in over), min(ref for _, ref in over)
    else:
        # A request: the average of every invoice since the rise, not only those above (review, p. 2)
        qty = sum((r.qty for r, _, _ in invoices), Decimal(0))
        price = sum((r.amount for r, _, _ in invoices), Decimal(0)) / qty
        reference = lowest = before
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
            "reference": _kopecks(reference),  # the contract (its highest), or the price before
            "reference_min": _kopecks(lowest),  # contracts of different days: the lowest of them
            "price": _kopecks(price),  # the average of every invoice of the window
            "since": since.isoformat(),
            "until": f.period_to.isoformat(),
            "invoices": lines[:MAX_INVOICES],
            "invoices_total": len(lines),
            "restaurants": len({x["restaurant"] for x in lines}),
            "extra": _kopecks(total),
            "growth_pct": str(((price / reference - 1) * 100).quantize(Decimal("0.1"))),
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
    tolerance = params.load(session).M3_CONTRACT_TOLERANCE
    out = []
    for f in found:
        if f.checked and (d := _draft(session, f, codes, tolerance)) is not None:
            out.append(d)
    return out
