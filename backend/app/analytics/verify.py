"""Checking a finding against the uploaded data (docs/12, «Проверка находок»).

The breakdown is computed again from the source rows by its own, simpler code path — not by the detector —
so a reviewer sees every number with the files it came from, and a disagreement with what the engine stored
shows up as a failed consistency check (the data changed since the run, or the engine is wrong).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import params
from app.analytics.drafts import pct, rub
from app.catalog.models import MenuItem, Product, RecipeLine
from app.catalog.recipes import Line, explode, lines_on
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.norms.service import load_norms
from app.operations.models import InventoryCount, Receipt, Sale, Transfer, WriteOff
from app.tenancy.models import Restaurant

UNITS = {"kg": "кг", "l": "л", "pcs": "шт"}
Q3 = Decimal("0.001")


def _q(v: Decimal, places: Decimal = Q3) -> str:
    return str(v.quantize(places, rounding=ROUND_HALF_UP))


def verify(session: Session, finding: Finding) -> dict[str, Any]:
    if finding.module == "M1" and finding.restaurant_id is not None:
        return _m1_restaurant(session, finding)
    if finding.module == "M1":
        return _m1_network(session, finding)
    return {
        "module": finding.module,
        "supported": False,
        "note": "Для этой находки расчет по шагам пока не собран — проверьте по исходным файлам",
    }


def _files(session: Session, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    return dict(
        session.execute(select(ImportBatch.id, ImportBatch.filename).where(ImportBatch.id.in_(ids))).all()
    )


def _m1_restaurant(session: Session, f: Finding) -> dict[str, Any]:
    ev = f.evidence or {}
    product = session.execute(select(Product).where(Product.code == ev["product"])).scalar_one()
    restaurant = session.get(Restaurant, f.restaurant_id)
    assert restaurant is not None and f.period_from and f.period_to
    unit = UNITS.get(product.base_unit, product.base_unit)
    first, end = f.period_from, f.period_to
    start = first - timedelta(days=1)  # the opening count is taken the evening before the period

    counts = {
        c.day: c
        for c in session.execute(
            select(InventoryCount).where(
                InventoryCount.restaurant_id == restaurant.id,
                InventoryCount.product_id == product.id,
                InventoryCount.day.in_([start, end]),
            )
        ).scalars()
    }
    receipts = list(
        session.execute(
            select(Receipt)
            .where(Receipt.restaurant_id == restaurant.id, Receipt.product_id == product.id)
            .where(Receipt.day >= first, Receipt.day <= end)
            .order_by(Receipt.day)
        ).scalars()
    )
    transfers = list(
        session.execute(
            select(Transfer)
            .where(Transfer.product_id == product.id, Transfer.day >= first, Transfer.day <= end)
            .where((Transfer.restaurant_id == restaurant.id) | (Transfer.to_restaurant_id == restaurant.id))
            .order_by(Transfer.day)
        ).scalars()
    )
    write_offs = list(
        session.execute(
            select(WriteOff)
            .where(WriteOff.restaurant_id == restaurant.id, WriteOff.product_id == product.id)
            .where(WriteOff.day >= first, WriteOff.day <= end)
            .order_by(WriteOff.day)
        ).scalars()
    )

    # Theoretical usage, dish by dish: portions sold × product per portion (semi-finished products opened).
    lines = [
        Line(r.menu_item_id or r.semi_product_id, r.product_id, r.gross_qty, r.valid_from)  # type: ignore[arg-type]
        for r in session.execute(select(RecipeLine)).scalars()
    ]
    menu = {m.id: m for m in session.execute(select(MenuItem)).scalars()}
    portions: dict[tuple[UUID, Decimal], Decimal] = defaultdict(Decimal)
    sale_batches: set[UUID] = set()
    per_portion_cache: dict[tuple[UUID, date], Decimal] = {}
    for s in session.execute(
        select(Sale).where(Sale.restaurant_id == restaurant.id, Sale.day >= first, Sale.day <= end)
    ).scalars():
        key = (s.menu_item_id, max((ln.valid_from for ln in lines if ln.valid_from <= s.day), default=s.day))
        if key not in per_portion_cache:
            per_portion_cache[key] = explode(s.menu_item_id, Decimal(1), lines_on(lines, key[1])).get(
                product.id, Decimal(0)
            )
        norm = per_portion_cache[key]
        if norm > 0:
            portions[(s.menu_item_id, norm)] += s.qty
            sale_batches.add(s.import_batch_id)
    dishes = sorted(
        (
            {
                "dish": menu[item].name,
                "portions": _q(qty, Decimal(1)),
                "per_portion": _q(norm),
                "usage": _q(qty * norm),
            }
            for (item, norm), qty in portions.items()
        ),
        key=lambda d: -Decimal(d["usage"]),
    )
    theory = sum((Decimal(d["usage"]) for d in dishes), Decimal(0))

    opening = counts[start].actual_qty if start in counts else None
    closing = counts[end].actual_qty if end in counts else None
    received = sum((r.qty for r in receipts), Decimal(0))
    moved_in = sum((t.qty for t in transfers if t.to_restaurant_id == restaurant.id), Decimal(0))
    moved_out = sum((t.qty for t in transfers if t.restaurant_id == restaurant.id), Decimal(0))
    written = sum((w.qty for w in write_offs), Decimal(0))
    paid = sum((r.amount for r in receipts), Decimal(0))
    unit_cost = paid / received if received > 0 else None

    files = _files(
        session,
        {c.import_batch_id for c in counts.values()}
        | {r.import_batch_id for r in receipts}
        | {t.import_batch_id for t in transfers}
        | {w.import_batch_id for w in write_offs}
        | sale_batches,
    )
    steps: list[dict[str, Any]] = [
        {
            "id": "opening",
            "label": f"Остаток на начало — инвентаризация {start:%d.%m}",
            "value": None if opening is None else _q(opening),
            "unit": unit,
            "rows": [
                {
                    "day": c.day.isoformat(),
                    "book": None if c.book_qty is None else _q(c.book_qty),
                    "actual": _q(c.actual_qty),
                    "file": files.get(c.import_batch_id),
                }
                for c in counts.values()
                if c.day == start
            ],
        },
        {
            "id": "receipts",
            "label": "Приход по накладным",
            "value": _q(received),
            "unit": unit,
            "rows": [
                {
                    "day": r.day.isoformat(),
                    "doc": r.doc_no,
                    "qty": _q(r.qty),
                    "amount": _q(r.amount, Decimal("0.01")),
                    "price": _q(r.amount / r.qty, Decimal("0.01")),
                    "file": files.get(r.import_batch_id),
                }
                for r in receipts
            ],
        },
        {
            "id": "transfers",
            "label": "Перемещения: пришло − ушло",
            "value": _q(moved_in - moved_out),
            "unit": unit,
            "rows": [
                {
                    "day": t.day.isoformat(),
                    "qty": _q(t.qty if t.to_restaurant_id == restaurant.id else -t.qty),
                    "file": files.get(t.import_batch_id),
                }
                for t in transfers
            ],
        },
        {
            "id": "closing",
            "label": f"Остаток на конец — инвентаризация {end:%d.%m}",
            "value": None if closing is None else _q(closing),
            "unit": unit,
            "rows": [
                {
                    "day": c.day.isoformat(),
                    "book": None if c.book_qty is None else _q(c.book_qty),
                    "actual": _q(c.actual_qty),
                    "file": files.get(c.import_batch_id),
                }
                for c in counts.values()
                if c.day == end
            ],
        },
        {
            "id": "theory",
            "label": "Расход по техкартам (продажи × норма)",
            "value": _q(theory),
            "unit": unit,
            "rows": dishes,
        },
        {
            "id": "write_offs",
            "label": "Оформленные списания",
            "value": _q(written),
            "unit": unit,
            "rows": [
                {
                    "day": w.day.isoformat(),
                    "qty": _q(w.qty),
                    "reason": w.reason,
                    "file": files.get(w.import_batch_id),
                }
                for w in write_offs
            ],
        },
    ]
    result: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    if opening is None or closing is None or theory <= 0:
        checks.append({"check": "Есть обе инвентаризации и продажи с техкартами", "ok": False})
        return {
            "module": "M1",
            "supported": True,
            "formula": FORMULA_M1,
            "steps": steps,
            "result": result,
            "checks": checks,
            "rules": rules,
        }

    actual = opening + received + moved_in - moved_out - closing
    unexplained = actual - theory - written
    share = unexplained / theory
    days = (end - first).days + 1
    result = [
        {
            "label": "Фактический расход A = начало + приход + перемещения − конец",
            "value": _q(actual),
            "unit": unit,
        },
        {
            "label": "Необъяснимый расход U = A − по техкартам − списания",
            "value": _q(unexplained),
            "unit": unit,
        },
        {"label": "Доля U от расхода по техкартам", "value": pct(share), "unit": ""},
        {
            "label": "Средняя цена закупки за период",
            "value": None if unit_cost is None else _q(unit_cost, Decimal("0.01")),
            "unit": f"₽/{unit}",
        },
    ]
    if unit_cost is not None:
        result.append({"label": "U в рублях за период", "value": rub(unexplained * unit_cost), "unit": ""})

    norms = load_norms(session)
    allowance = norms.loss_allowance(product.category) / 100
    benchmark = Decimal(ev.get("benchmark", allowance))
    effect = None if unit_cost is None else (share - benchmark) * theory * unit_cost * 30 / days
    rules = [
        {
            "rule": f"Расход выше допуска категории «{product.category or 'без категории'}»",
            "value": pct(share),
            "threshold": pct(allowance),
            "passed": share > allowance,
        },
        {
            "rule": "Расход выше ориентира (большее из допуска и медианы сети)",
            "value": pct(share),
            "threshold": pct(benchmark),
            "passed": share > benchmark,
        },
    ]
    if ev.get("z") is not None:
        rules.append(
            {
                "rule": "Ресторан выбивается из сети (robust z-score)",
                "value": ev["z"],
                "threshold": str(params.M1_Z),
                "passed": Decimal(ev["z"]) > params.M1_Z,
            }
        )
    if effect is not None:
        rules.append(
            {
                "rule": "Потери существенны, ₽ в месяц сверх ориентира",
                "value": rub(effect),
                "threshold": rub(params.M1_MATERIALITY_RUB_MONTH),
                "passed": effect >= params.M1_MATERIALITY_RUB_MONTH,
            }
        )

    stored = next((p for p in reversed(ev.get("periods", [])) if p["to"] == end.isoformat()), None)
    checks = [
        {"check": "Обе инвентаризации загружены", "ok": True},
        {
            "check": "Цена закупки есть в периоде",
            "ok": unit_cost is not None,
            "note": None if unit_cost is not None else "сумма оценена по прошлым закупкам или по сети",
        },
        {
            "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
            "ok": stored is not None and abs(Decimal(stored["share"]) - share) < Decimal("0.0005"),
            "note": None
            if stored is None
            else f"движок: {pct(Decimal(stored['share']))}, пересчет: {pct(share)}",
        },
        {
            "check": "Сумма в находке совпадает с пересчетом",
            "ok": effect is not None
            and f.effect_rub_month is not None
            and abs(effect - f.effect_rub_month) <= max(Decimal(50), f.effect_rub_month / 100),
            "note": None
            if effect is None
            else f"в находке: {rub(f.effect_rub_month or Decimal(0))}, пересчет: {rub(effect)}",
        },
    ]
    return {
        "module": "M1",
        "supported": True,
        "formula": FORMULA_M1,
        "object": product.name,
        "restaurant": restaurant.name,
        "period": [first.isoformat(), end.isoformat()],
        "steps": steps,
        "result": result,
        "rules": rules,
        "checks": checks,
        "history": ev.get("periods", []),
        "interpretation": INTERPRETATION_M1,
    }


def _m1_network(session: Session, f: Finding) -> dict[str, Any]:
    ev = f.evidence or {}
    allowance = Decimal(ev["allowance"])
    shares = {code: Decimal(v) for code, v in ev.get("restaurants", {}).items()}
    over = [c for c, s in shares.items() if s > allowance]
    m = Decimal(ev["median_share"])
    return {
        "module": "M1",
        "supported": True,
        "formula": FORMULA_M1,
        "object": ev["product"],
        "period": [
            f.period_from.isoformat() if f.period_from else None,
            f.period_to.isoformat() if f.period_to else None,
        ],
        "steps": [
            {
                "id": "restaurants",
                "label": "Необъяснимый расход по ресторанам, доля от расхода по техкартам",
                "value": None,
                "unit": "",
                "rows": [
                    {"restaurant": c, "share": pct(s), "over": s > allowance}
                    for c, s in sorted(shares.items())
                ],
            }
        ],
        "result": [{"label": "Медиана сети", "value": pct(m), "unit": ""}],
        "rules": [
            {
                "rule": "Доля ресторанов сверх допуска",
                "value": f"{len(over)} из {len(shares)}",
                "threshold": f"{pct(params.M1_NET_SHARE, 0)}",
                "passed": len(shares) > 0 and Decimal(len(over)) / len(shares) >= params.M1_NET_SHARE,
            },
            {
                "rule": "Медиана сети выше допуска",
                "value": pct(m - allowance),
                "threshold": pct(params.M1_NET_EXCESS),
                "passed": m - allowance >= params.M1_NET_EXCESS,
            },
        ],
        "checks": [],
        "interpretation": INTERPRETATION_M1_NET,
    }


FORMULA_M1 = (
    "U = (остаток на начало + приход + перемещения − остаток на конец) − расход по техкартам − списания"
)
INTERPRETATION_M1 = [
    "Перерасход в одном ресторане: нарушение техкарты (порции, выход при обработке), неоформленные списания, "
    "хищение.",
    "Если перерасход растет от периода к периоду — проблема усиливается, а не случайность.",
    "Прежде чем подтверждать: проверьте, что инвентаризации полные (товар посчитан на всех складах) и все "
    "накладные загружены.",
]
INTERPRETATION_M1_NET = [
    "Одинаковый перерасход во всей сети — почти всегда ошибка техкарты (устаревший выход, другой поставщик), "
    "а не кухонь.",
    "Деньги при этом не теряются, но фудкост и потери по сети считаются неверно, а перерасход в отдельных "
    "ресторанах маскируется.",
]
