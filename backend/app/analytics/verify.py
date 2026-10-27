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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import params
from app.analytics.drafts import pct, rub
from app.analytics.stats import med
from app.catalog.models import ContractPrice, MenuItem, Product, RecipeLine, Supplier
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
    if finding.module == "M2":
        return _m2(session, finding)
    if finding.module == "M3" and finding.restaurant_id is not None:
        return _m3(session, finding)
    if finding.module == "M3" and (finding.evidence or {}).get("kind") == "growth":
        return _m3_growth(session, finding)
    if finding.module == "M3" and (finding.evidence or {}).get("kind") == "contract":
        return _m3_contract(session, finding)
    if finding.module == "M7" and (finding.evidence or {}).get("kind") in ("no_recipe", "gap"):
        return _m7(session, finding)
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
    cfg = params.load(session)
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

    if ev.get("direction") == "under":
        rules, effect = _m1_under_rules(ev, share, unexplained, unit_cost, days, cfg), None
    else:
        rules, effect = _m1_over_rules(session, product, ev, share, theory, unit_cost, days, cfg)
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
    ]
    if ev.get("direction") != "under":
        checks.append(
            {
                "check": "Сумма в находке совпадает с пересчетом",
                "ok": effect is not None
                and f.effect_rub_month is not None
                and abs(effect - f.effect_rub_month) <= max(Decimal(50), f.effect_rub_month / 100),
                "note": None
                if effect is None
                else f"в находке: {rub(f.effect_rub_month or Decimal(0))}, пересчет: {rub(effect)}",
            }
        )
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
        "interpretation": INTERPRETATION_M1_UNDER if ev.get("direction") == "under" else INTERPRETATION_M1,
    }


def _m1_over_rules(
    session: Session,
    product: Product,
    ev: dict[str, Any],
    share: Decimal,
    theory: Decimal,
    unit_cost: Decimal | None,
    days: int,
    cfg: params.EngineParams,
) -> tuple[list[dict[str, Any]], Decimal | None]:
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
                "threshold": str(cfg.M1_Z),
                "passed": Decimal(ev["z"]) > cfg.M1_Z,
            }
        )
    if effect is not None:
        rules.append(
            {
                "rule": "Потери существенны, ₽ в месяц сверх ориентира",
                "value": rub(effect),
                "threshold": rub(cfg.M1_MATERIALITY_RUB_MONTH),
                "passed": effect >= cfg.M1_MATERIALITY_RUB_MONTH,
            }
        )

    return rules, effect


def _m1_under_rules(
    ev: dict[str, Any],
    share: Decimal,
    unexplained: Decimal,
    unit_cost: Decimal | None,
    days: int,
    cfg: params.EngineParams,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {
            "rule": "Расход меньше техкарты больше чем на порог",
            "value": pct(-share),
            "threshold": pct(cfg.M1_UNDER),
            "passed": share < -cfg.M1_UNDER,
        }
    ]
    if ev.get("z") is not None:
        rules.append(
            {
                "rule": "Ресторан выбивается из сети вниз (robust z-score)",
                "value": ev["z"],
                "threshold": f"−{cfg.M1_Z}",
                "passed": Decimal(ev["z"]) < -cfg.M1_Z,
            }
        )
    if unit_cost is not None:
        shortfall = -unexplained * unit_cost * 30 / days
        rules.append(
            {
                "rule": "Недостающий товар существенен, ₽ в месяц",
                "value": rub(shortfall),
                "threshold": rub(cfg.M1_MATERIALITY_RUB_MONTH),
                "passed": shortfall >= cfg.M1_MATERIALITY_RUB_MONTH,
            }
        )
    return rules


def _m1_share(
    session: Session, restaurant_id: UUID, product: Product, first: date, end: date, lines: list[Line]
) -> Decimal | None:
    """U% of one restaurant and period, recomputed from the stored rows (as in `_m1_restaurant`)."""
    start = first - timedelta(days=1)
    counts: dict[date, Decimal] = {
        day: qty
        for day, qty in session.execute(
            select(InventoryCount.day, InventoryCount.actual_qty).where(
                InventoryCount.restaurant_id == restaurant_id,
                InventoryCount.product_id == product.id,
                InventoryCount.day.in_([start, end]),
            )
        ).all()
    }
    if start not in counts or end not in counts:
        return None

    def total(model: Any, *where: Any) -> Decimal:
        rows = session.execute(
            select(model.qty).where(
                model.product_id == product.id, model.day >= first, model.day <= end, *where
            )
        ).scalars()
        return sum(rows, Decimal(0))

    received = total(Receipt, Receipt.restaurant_id == restaurant_id)
    moved_in = total(Transfer, Transfer.to_restaurant_id == restaurant_id)
    moved_out = total(Transfer, Transfer.restaurant_id == restaurant_id)
    written = total(WriteOff, WriteOff.restaurant_id == restaurant_id)
    theory = Decimal(0)
    per_portion: dict[tuple[UUID, date], Decimal] = {}
    for item, day, qty in session.execute(
        select(Sale.menu_item_id, Sale.day, Sale.qty).where(
            Sale.restaurant_id == restaurant_id, Sale.day >= first, Sale.day <= end
        )
    ).all():
        version = max((ln.valid_from for ln in lines if ln.valid_from <= day), default=day)
        if (item, version) not in per_portion:
            opened = explode(item, Decimal(1), lines_on(lines, version))
            per_portion[(item, version)] = opened.get(product.id, Decimal(0))
        theory += qty * per_portion[(item, version)]
    if theory <= 0:
        return None
    actual = counts[start] + received + moved_in - moved_out - counts[end]
    return (actual - theory - written) / theory


def _m1_network(session: Session, f: Finding) -> dict[str, Any]:
    """The recipe looks wrong across the network: every restaurant's share recomputed from its rows."""
    cfg = params.load(session)
    ev = f.evidence or {}
    allowance = Decimal(ev["allowance"])
    stored = {code: Decimal(v) for code, v in ev.get("restaurants", {}).items()}
    product = session.execute(select(Product).where(Product.code == ev["product"])).scalar_one_or_none()
    ids = {code: rid for rid, code in session.execute(select(Restaurant.id, Restaurant.code)).all()}
    lines = [
        Line(r.menu_item_id or r.semi_product_id, r.product_id, r.gross_qty, r.valid_from)  # type: ignore[arg-type]
        for r in session.execute(select(RecipeLine)).scalars()
    ]
    # Findings recorded before each restaurant's own period was stored: the finding's period for all.
    periods: dict[str, list[str]] = ev.get("periods") or {
        code: [f.period_from.isoformat(), f.period_to.isoformat()]
        for code in stored
        if f.period_from and f.period_to
    }
    shares: dict[str, Decimal] = {}
    for code, (first, end) in periods.items():
        if product is None or code not in ids:
            continue
        share = _m1_share(
            session, ids[code], product, date.fromisoformat(first), date.fromisoformat(end), lines
        )
        if share is not None:
            shares[code] = share
    over = [c for c, s in shares.items() if s > allowance]
    m = med(list(shares.values())) if shares else Decimal(0)
    missing = sorted(set(stored) - set(shares))
    mismatched = sorted(
        c for c, s in shares.items() if c in stored and abs(stored[c] - s) >= Decimal("0.0005")
    )
    return {
        "module": "M1",
        "supported": True,
        "formula": FORMULA_M1,
        "object": product.name if product else ev["product"],
        "period": [
            f.period_from.isoformat() if f.period_from else None,
            f.period_to.isoformat() if f.period_to else None,
        ],
        "steps": [
            {
                "id": "restaurants",
                "label": "Необъяснимый расход по ресторанам, доля от расхода по техкартам (из строк)",
                "value": None,
                "unit": "",
                "rows": [
                    {
                        "restaurant": c,
                        "day": f"{periods[c][0]} – {periods[c][1]}",
                        "share": pct(s),
                        "over": s > allowance,
                    }
                    for c, s in sorted(shares.items())
                ],
            }
        ],
        "result": [{"label": "Медиана сети", "value": pct(m), "unit": ""}],
        "rules": [
            {
                "rule": "Доля ресторанов сверх допуска",
                "value": f"{len(over)} из {len(shares)}",
                "threshold": f"{pct(cfg.M1_NET_SHARE, 0)}",
                "passed": len(shares) > 0 and Decimal(len(over)) / len(shares) >= cfg.M1_NET_SHARE,
            },
            {
                "rule": "Медиана сети выше допуска",
                "value": pct(m - allowance),
                "threshold": pct(cfg.M1_NET_EXCESS),
                "passed": m - allowance >= cfg.M1_NET_EXCESS,
            },
        ],
        "checks": [
            {
                "check": "Все рестораны находки пересчитаны из исходных строк",
                "ok": not missing,
                "note": None if not missing else f"не пересчитаны: {', '.join(missing)}",
            },
            {
                "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
                "ok": not mismatched,
                "note": None if not mismatched else f"расходятся: {', '.join(mismatched)}",
            },
        ],
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
INTERPRETATION_M1_UNDER = [
    "Расход меньше техкарты: на раздаче кладут меньше положенного, часть прихода не проведена или товар "
    "заменяют другим (пересорт).",
    "Денег это не теряет, но гость может получать не то блюдо, которое заложено в меню.",
    "Прежде чем подтверждать: проверьте, что инвентаризации полные и что все накладные и перемещения "
    "загружены.",
]
INTERPRETATION_M1_NET = [
    "Одинаковый перерасход во всей сети — почти всегда ошибка техкарты (устаревший выход, другой поставщик), "
    "а не кухонь.",
    "Деньги при этом не теряются, но фудкост и потери по сети считаются неверно, а перерасход в отдельных "
    "ресторанах маскируется.",
]


def _m3(session: Session, f: Finding) -> dict[str, Any]:
    cfg = params.load(session)
    ev = f.evidence or {}
    product = session.execute(select(Product).where(Product.code == ev["product"])).scalar_one()
    restaurant = session.get(Restaurant, f.restaurant_id)
    assert restaurant is not None and f.period_from and f.period_to
    unit = UNITS.get(product.base_unit, product.base_unit)
    start, end = f.period_from, f.period_to
    suppliers = dict(session.execute(select(Supplier.id, Supplier.name)).all())
    codes = dict(session.execute(select(Restaurant.id, Restaurant.code)).all())
    receipts = list(
        session.execute(
            select(Receipt)
            .where(Receipt.product_id == product.id, Receipt.day >= start, Receipt.day <= end)
            .order_by(Receipt.day)
        ).scalars()
    )
    own = [r for r in receipts if r.restaurant_id == restaurant.id]
    files = _files(session, {r.import_batch_id for r in own})
    # Every other restaurant's weighted price in the same window: the network the restaurant is compared with.
    totals: dict[UUID, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
    for r in receipts:
        t = totals[r.restaurant_id]
        t[0] += r.amount
        t[1] += r.qty
        t[2] += 1
    others = {
        rid: t[0] / t[1] for rid, t in totals.items() if rid != restaurant.id and t[2] >= cfg.M3_MIN_RECEIPTS
    }
    qty = sum((r.qty for r in own), Decimal(0))
    paid = sum((r.amount for r in own), Decimal(0))
    steps: list[dict[str, Any]] = [
        {
            "id": "own",
            "label": f"Закупки ресторана за {start:%d.%m}–{end:%d.%m}",
            "value": _q(qty),
            "unit": unit,
            "rows": [
                {
                    "day": r.day.isoformat(),
                    "doc": r.doc_no,
                    "supplier": suppliers.get(r.supplier_id, "—") if r.supplier_id else "—",
                    "qty": _q(r.qty),
                    "amount": _q(r.amount, Decimal("0.01")),
                    "price": _q(r.amount / r.qty, Decimal("0.01")),
                    "file": files.get(r.import_batch_id),
                }
                for r in own
            ],
        },
        {
            "id": "network",
            "label": "Средняя цена в других ресторанах сети за то же время",
            "value": None,
            "unit": "",
            "rows": [
                {"restaurant": codes.get(rid, "—"), "price": _q(p, Decimal("0.01"))}
                for rid, p in sorted(others.items(), key=lambda kv: codes.get(kv[0], ""))
            ],
        },
    ]
    if qty <= 0 or len(others) < 2:
        return {
            "module": "M3",
            "supported": True,
            "steps": steps,
            "result": [],
            "rules": [],
            "checks": [{"check": "Есть закупки ресторана и не меньше двух других ресторанов", "ok": False}],
        }
    price = paid / qty
    bench = Decimal(med(list(others.values())))
    share = price / bench - 1
    days = (end - start).days + 1
    overpay = (price - bench) * qty
    effect = overpay * 30 / days
    result = [
        {
            "label": "Средняя цена ресторана (сумма / количество)",
            "value": _q(price, Decimal("0.01")),
            "unit": f"₽/{unit}",
        },
        {
            "label": "Типичная цена сети (медиана других ресторанов)",
            "value": _q(bench, Decimal("0.01")),
            "unit": f"₽/{unit}",
        },
        {"label": "Дороже сети", "value": pct(share), "unit": ""},
        {"label": f"Переплата за {days} дней", "value": rub(overpay), "unit": ""},
        {"label": "Переплата в месяц", "value": rub(effect), "unit": ""},
    ]
    rules = [
        {
            "rule": "Цена выше типичной цены сети",
            "value": pct(share),
            "threshold": pct(cfg.M3_OVERPAY, 0),
            "passed": share > cfg.M3_OVERPAY,
        },
        {
            "rule": "Переплата существенна, ₽ в месяц",
            "value": rub(effect),
            "threshold": rub(cfg.M3_MATERIALITY_RUB_MONTH),
            "passed": effect >= cfg.M3_MATERIALITY_RUB_MONTH,
        },
    ]
    if ev.get("z") is not None:
        rules.insert(
            1,
            {
                "rule": "Цена выбивается из сети (robust z-score)",
                "value": ev["z"],
                "threshold": str(cfg.M3_Z),
                "passed": Decimal(ev["z"]) > cfg.M3_Z,
            },
        )
    checks = [
        {"check": f"Закупок ресторана в окне: {len(own)}", "ok": len(own) >= cfg.M3_MIN_RECEIPTS},
        {
            "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
            "ok": abs(Decimal(ev["share"]) - share) < Decimal("0.0005"),
            "note": f"движок: {pct(Decimal(ev['share']))}, пересчет: {pct(share)}",
        },
        {
            "check": "Сумма в находке совпадает с пересчетом",
            "ok": f.effect_rub_month is not None
            and abs(effect - f.effect_rub_month) <= max(Decimal(50), f.effect_rub_month / 100),
            "note": f"в находке: {rub(f.effect_rub_month or Decimal(0))}, пересчет: {rub(effect)}",
        },
    ]
    return {
        "module": "M3",
        "supported": True,
        "formula": FORMULA_M3,
        "object": product.name,
        "restaurant": restaurant.name,
        "period": [start.isoformat(), end.isoformat()],
        "steps": steps,
        "result": result,
        "rules": rules,
        "checks": checks,
        "interpretation": INTERPRETATION_M3,
    }


FORMULA_M3 = (
    "Переплата = (средняя цена ресторана − типичная цена сети) × количество; "
    "средняя цена = сумма по накладным / количество за 8 недель"
)
INTERPRETATION_M3 = [
    "Другой поставщик дороже, чем у остальных: чаще всего срочные закупки, когда товар заканчивается "
    "раньше поставки.",
    "Тот же поставщик продает дороже, чем другим ресторанам: повод запросить единую цену или договор "
    "на всю сеть.",
    "Прежде чем подтверждать: проверьте, что сравниваются одинаковые товары (тот же вид, фасовка, качество).",
]


def _network_prices(session: Session, start: date, end: date) -> dict[UUID, Decimal]:
    totals: dict[UUID, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for product, amount, qty in session.execute(
        select(Receipt.product_id, Receipt.amount, Receipt.qty).where(
            Receipt.day >= start, Receipt.day <= end
        )
    ).all():
        totals[product][0] += amount
        totals[product][1] += qty
    return {p: a / q for p, (a, q) in totals.items() if q > 0}


def _m2(session: Session, f: Finding) -> dict[str, Any]:
    cfg = params.load(session)
    ev = f.evidence or {}
    item = session.execute(select(MenuItem).where(MenuItem.code == ev["menu_item"])).scalar_one()
    assert f.period_from and f.period_to
    start, end = f.period_from, f.period_to
    before_start, before_end = (date.fromisoformat(d) for d in ev["before"])
    lines = [
        Line(r.menu_item_id or r.semi_product_id, r.product_id, r.gross_qty, r.valid_from)  # type: ignore[arg-type]
        for r in session.execute(select(RecipeLine)).scalars()
    ]
    need = explode(item.id, Decimal(1), lines_on(lines, end))
    need_before = explode(item.id, Decimal(1), lines_on(lines, before_end))
    now, before = _network_prices(session, start, end), _network_prices(session, before_start, before_end)
    products = {
        p.id: p for p in session.execute(select(Product).where(Product.id.in_(need.keys()))).scalars()
    }
    rows = []
    for pid, qty in sorted(need.items(), key=lambda kv: -(kv[1] * now.get(kv[0], Decimal(0)))):
        p = products[pid]
        unit = UNITS.get(p.base_unit, p.base_unit)
        rows.append(
            {
                "product": p.name,
                "per_portion": f"{_q(qty)} {unit}",
                "price": None if pid not in now else _q(now[pid], Decimal("0.01")),
                "cost": None if pid not in now else _q(qty * now[pid], Decimal("0.01")),
                "price_before": None if pid not in before else _q(before[pid], Decimal("0.01")),
                "cost_before": None
                if pid not in before
                else _q(need_before.get(pid, qty) * before[pid], Decimal("0.01")),
            }
        )
    revenue = sum(
        (
            r
            for (r,) in session.execute(
                select(Sale.revenue).where(Sale.menu_item_id == item.id, Sale.day >= start, Sale.day <= end)
            ).all()
        ),
        Decimal(0),
    )
    steps: list[dict[str, Any]] = [
        {
            "id": "recipe",
            "label": f"Себестоимость порции по техкарте: цены сети за {start:%d.%m}–{end:%d.%m} "
            f"и квартал назад ({before_start:%d.%m}–{before_end:%d.%m})",
            "value": None,
            "unit": "",
            "rows": rows,
        },
        {
            "id": "revenue",
            "label": "Выручка блюда по сети за то же время",
            "value": rub(revenue),
            "unit": "",
            "rows": [],
        },
    ]
    if any(p not in now for p in need) or not need:
        return {
            "module": "M2",
            "supported": True,
            "steps": steps,
            "result": [],
            "rules": [],
            "checks": [{"check": "Есть цены закупки всех ингредиентов", "ok": False}],
        }
    cost = sum((q * now[p] for p, q in need.items()), Decimal(0))
    cost_before = (
        sum((q * before[p] for p, q in need_before.items()), Decimal(0))
        if all(p in before for p in need_before)
        else None
    )
    price = item.price or Decimal(ev["price"])
    food_cost = cost / price
    norms = load_norms(session)
    target = norms.food_cost_target(item.category) / 100
    days = (end - start).days + 1
    potential = (food_cost - target) * revenue * cfg.M2_KEEP * 30 / days
    result = [
        {"label": "Себестоимость порции сейчас", "value": rub(cost), "unit": ""},
        {
            "label": "Себестоимость порции квартал назад",
            "value": None if cost_before is None else rub(cost_before),
            "unit": "",
        },
        {"label": "Цена в меню", "value": rub(price), "unit": ""},
        {"label": "Фудкост блюда", "value": pct(food_cost), "unit": ""},
        {
            "label": f"Цель для категории «{item.category or 'без категории'}»",
            "value": pct(target, 0),
            "unit": "",
        },
        {
            "label": "Цена, при которой фудкост вернется к цели",
            "value": rub(Decimal(ev["suggested_price"])),
            "unit": "",
        },
        {
            "label": "Потенциал в месяц (половина разницы — консервативно)",
            "value": rub(potential),
            "unit": "",
        },
    ]
    rules = [
        {
            "rule": "Фудкост блюда выше цели",
            "value": pct(food_cost),
            "threshold": pct(target, 0),
            "passed": food_cost > target,
        },
        {
            "rule": "Потенциал существенный, ₽ в месяц",
            "value": rub(potential),
            "threshold": rub(cfg.M2_MATERIALITY_RUB_MONTH),
            "passed": potential >= cfg.M2_MATERIALITY_RUB_MONTH,
        },
    ]
    checks = [
        {
            "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
            "ok": abs(Decimal(ev["food_cost"]) - food_cost) < Decimal("0.0005"),
            "note": f"движок: {pct(Decimal(ev['food_cost']))}, пересчет: {pct(food_cost)}",
        },
        {
            "check": "Сумма в находке совпадает с пересчетом",
            "ok": f.effect_rub_month is not None
            and abs(potential - f.effect_rub_month) <= max(Decimal(50), f.effect_rub_month / 100),
            "note": f"в находке: {rub(f.effect_rub_month or Decimal(0))}, пересчет: {rub(potential)}",
        },
    ]
    return {
        "module": "M2",
        "supported": True,
        "formula": FORMULA_M2,
        "object": item.name,
        "restaurant": "Вся сеть",
        "period": [start.isoformat(), end.isoformat()],
        "steps": steps,
        "result": result,
        "rules": rules,
        "checks": checks,
        "interpretation": INTERPRETATION_M2,
    }


FORMULA_M2 = (
    "Фудкост блюда = себестоимость порции по техкарте и текущим ценам закупки / цена в меню; "
    "потенциал = (фудкост − цель) × выручка блюда × 0,5"
)
INTERPRETATION_M2 = [
    "Цена в меню едина для сети, поэтому находка — для управляющей компании.",
    "Половина разницы — консервативная оценка: после подорожания часть гостей закажет другое блюдо.",
    "Прежде чем подтверждать: убедитесь, что рост цены ингредиента не разовый (одна дорогая поставка).",
]


def _m3_growth(session: Session, f: Finding) -> dict[str, Any]:
    cfg = params.load(session)
    ev = f.evidence or {}
    product = session.execute(select(Product).where(Product.code == ev["product"])).scalar_one()
    assert f.period_from and f.period_to
    unit = UNITS.get(product.base_unit, product.base_unit)
    before_start, before_end = (date.fromisoformat(d) for d in ev["before"])
    codes = dict(session.execute(select(Restaurant.id, Restaurant.code)).all())

    def per_restaurant(start: date, end: date) -> dict[UUID, tuple[Decimal, Decimal]]:
        out: dict[UUID, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
        for rid, amount, qty in session.execute(
            select(Receipt.restaurant_id, Receipt.amount, Receipt.qty).where(
                Receipt.product_id == product.id, Receipt.day >= start, Receipt.day <= end
            )
        ).all():
            out[rid][0] += amount
            out[rid][1] += qty
        return {rid: (a, q) for rid, (a, q) in out.items()}

    now, before = per_restaurant(f.period_from, f.period_to), per_restaurant(before_start, before_end)
    qty = sum((q for _, q in now.values()), Decimal(0))
    p_now = sum((a for a, _ in now.values()), Decimal(0)) / qty if qty else Decimal(0)
    q_before = sum((q for _, q in before.values()), Decimal(0))
    p_before = sum((a for a, _ in before.values()), Decimal(0)) / q_before if q_before else Decimal(0)
    growth = p_now / p_before - 1 if p_before else Decimal(0)
    days = (f.period_to - f.period_from).days + 1
    effect = (p_now - p_before) * qty * 30 / days
    steps = [
        {
            "id": "network",
            "label": f"Средняя цена по ресторанам: {f.period_from:%d.%m}–{f.period_to:%d.%m} "
            f"и квартал назад ({before_start:%d.%m}–{before_end:%d.%m})",
            "value": None,
            "unit": "",
            "rows": [
                {
                    "restaurant": codes.get(rid, "—"),
                    "price_before": None
                    if rid not in before
                    else _q(before[rid][0] / before[rid][1], Decimal("0.01")),
                    "price": _q(a / q, Decimal("0.01")),
                    "qty": _q(q),
                }
                for rid, (a, q) in sorted(now.items(), key=lambda kv: codes.get(kv[0], ""))
            ],
        }
    ]
    result = [
        {"label": "Цена сети сейчас", "value": _q(p_now, Decimal("0.01")), "unit": f"₽/{unit}"},
        {"label": "Цена сети квартал назад", "value": _q(p_before, Decimal("0.01")), "unit": f"₽/{unit}"},
        {"label": "Рост", "value": pct(growth), "unit": ""},
        {"label": "Сверх прежней цены в месяц", "value": rub(effect), "unit": ""},
    ]
    rules = [
        {
            "rule": "Цена выросла по всей сети",
            "value": pct(growth),
            "threshold": pct(cfg.M3_NET_GROWTH, 0),
            "passed": growth > cfg.M3_NET_GROWTH,
        },
        {
            "rule": "Сумма существенная, ₽ в месяц",
            "value": rub(effect),
            "threshold": rub(cfg.M3_MATERIALITY_RUB_MONTH),
            "passed": effect >= cfg.M3_MATERIALITY_RUB_MONTH,
        },
    ]
    checks = [
        {
            "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
            "ok": abs(Decimal(ev["growth"]) - growth) < Decimal("0.0005"),
            "note": f"движок: {pct(Decimal(ev['growth']))}, пересчет: {pct(growth)}",
        },
        {"check": "Договорной цены на этот товар нет — сравниваем с прошлым кварталом", "ok": True},
    ]
    return {
        "module": "M3",
        "supported": True,
        "object": product.name,
        "restaurant": "Вся сеть",
        "formula": "Рост = средняя цена сети за 4 недели / та же цена квартал назад − 1; "
        "сумма = (цена сейчас − цена тогда) × количество",
        "steps": steps,
        "result": result,
        "rules": rules,
        "checks": checks,
        "interpretation": [
            "Рост по всей сети — это не ошибка ресторанов, а условия поставщика или рынка.",
            "Если с поставщиком есть договор, загрузите договорные цены: тогда движок сравнит накладные "
            "с договором.",
            "Рост себестоимости отражается на фудкосте блюд — смотрите находки M2.",
        ],
    }


def _m3_contract(session: Session, f: Finding) -> dict[str, Any]:
    """Invoices above the contract, recomputed from the stored receipts and contract prices."""
    cfg = params.load(session)
    ev = f.evidence or {}
    assert f.period_from and f.period_to
    product = session.execute(select(Product).where(Product.code == ev["product"])).scalar_one_or_none()
    supplier = session.execute(select(Supplier).where(Supplier.name == ev["supplier"])).scalars().first()
    if product is None or supplier is None:
        return {"module": "M3", "supported": False, "note": "Товар или поставщик больше не в справочнике"}
    unit = UNITS.get(product.base_unit, product.base_unit)
    contracts = list(
        session.execute(
            select(ContractPrice).where(
                ContractPrice.supplier_id == supplier.id, ContractPrice.product_id == product.id
            )
        ).scalars()
    )
    codes = dict(session.execute(select(Restaurant.id, Restaurant.code)).all())
    receipts = list(
        session.execute(
            select(Receipt)
            .where(
                Receipt.supplier_id == supplier.id,
                Receipt.product_id == product.id,
                Receipt.day >= f.period_from,
                Receipt.day <= f.period_to,
                Receipt.qty > 0,
            )
            .order_by(Receipt.day)
        ).scalars()
    )
    files = _files(session, {r.import_batch_id for r in receipts})
    over: list[tuple[Receipt, Decimal]] = []
    for r in receipts:
        valid = [
            c for c in contracts if c.valid_from <= r.day and (c.valid_to is None or r.day <= c.valid_to)
        ]
        if not valid:
            continue
        price = max(valid, key=lambda c: c.valid_from).price
        if r.amount / r.qty > price * (1 + cfg.M3_CONTRACT_TOLERANCE):
            over.append((r, price))
    overpay = sum((r.amount - p * r.qty for r, p in over), Decimal(0))
    days = (f.period_to - f.period_from).days + 1
    effect = (overpay * 30 / days).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    contract_price = max((p for _, p in over), default=Decimal(0))
    qty = sum((r.qty for r, _ in over), Decimal(0))
    paid = sum((r.amount for r, _ in over), Decimal(0)) / qty if qty else Decimal(0)
    steps = [
        {
            "id": "receipts",
            "label": f"Накладные «{supplier.name}» выше договорной цены",
            "value": rub(overpay),
            "unit": "",
            "rows": [
                {
                    "day": r.day.isoformat(),
                    "restaurant": codes.get(r.restaurant_id, "—"),
                    "doc": r.doc_no,
                    "qty": _q(r.qty),
                    "price": _q(r.amount / r.qty, Decimal("0.01")),
                    "contract": _q(p, Decimal("0.01")),
                    "overpay": _q(r.amount - p * r.qty, Decimal("0.01")),
                    "file": files.get(r.import_batch_id),
                }
                for r, p in over
            ],
        }
    ]
    money = Decimal("0.01")
    result = [
        {"label": "Цена по договору", "value": _q(contract_price, money), "unit": f"₽/{unit}"},
        {"label": "Средняя цена в накладных выше договора", "value": _q(paid, money), "unit": f"₽/{unit}"},
        {"label": "Накладных выше договора", "value": str(len(over)), "unit": ""},
        {"label": "Переплата в месяц", "value": rub(effect), "unit": ""},
    ]
    rules = [
        {
            "rule": "Цена в накладной выше договорной сверх допуска на округления",
            "value": f"{len(over)} накладных",
            "threshold": pct(cfg.M3_CONTRACT_TOLERANCE, 0),
            "passed": bool(over),
        },
        {
            "rule": "Переплата существенная, ₽ в месяц",
            "value": rub(effect),
            "threshold": rub(cfg.M3_MATERIALITY_RUB_MONTH),
            "passed": effect >= cfg.M3_MATERIALITY_RUB_MONTH,
        },
    ]
    checks = [
        {"check": "Договорная цена загружена на этот период", "ok": bool(contracts)},
        {
            "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
            "ok": abs(Decimal(ev["overpay"]) - overpay) < Decimal(1),
            "note": f"движок: {rub(Decimal(ev['overpay']))}, пересчет: {rub(overpay)}",
        },
        {
            "check": "Сумма в находке совпадает с пересчетом",
            "ok": f.effect_rub_month is not None and abs(effect - f.effect_rub_month) <= Decimal(1),
            "note": f"в находке: {rub(f.effect_rub_month or Decimal(0))}, пересчет: {rub(effect)}",
        },
    ]
    return {
        "module": "M3",
        "supported": True,
        "object": product.name,
        "restaurant": "Вся сеть",
        "period": [f.period_from.isoformat(), f.period_to.isoformat()],
        "formula": "Переплата = Σ (сумма накладной − договорная цена × количество) "
        "по накладным выше договора",
        "steps": steps,
        "result": result,
        "rules": rules,
        "checks": checks,
        "interpretation": [
            "Проверьте, не менялся ли договор: новую цену загрузите файлом «Договорные цены».",
            "Переплату по накладным можно предъявить поставщику: номера документов — в таблице.",
        ],
    }


def _m7(session: Session, f: Finding) -> dict[str, Any]:
    """Data quality: the same facts recomputed from the stored rows."""
    ev = f.evidence or {}
    cfg = params.load(session)
    codes = dict(session.execute(select(Restaurant.id, Restaurant.code)).all())
    if ev.get("kind") == "no_recipe":
        item = session.execute(select(MenuItem).where(MenuItem.code == ev["menu_item"])).scalar_one_or_none()
        if item is None:
            return {"module": "M7", "supported": False, "note": "Блюда больше нет в справочнике"}
        first, end = (date.fromisoformat(d) for d in ev["window"])
        recipe_from = session.execute(
            select(func.min(RecipeLine.valid_from)).where(RecipeLine.menu_item_id == item.id)
        ).scalar_one_or_none()
        sales = session.execute(
            select(Sale.restaurant_id, func.sum(Sale.qty), func.sum(Sale.revenue))
            .where(Sale.menu_item_id == item.id, Sale.day >= first, Sale.day <= end)
            .group_by(Sale.restaurant_id)
        ).all()
        total = session.execute(
            select(func.sum(Sale.revenue)).where(Sale.day >= first, Sale.day <= end)
        ).scalar_one() or Decimal(0)
        revenue = sum((r for _, _, r in sales), Decimal(0))
        share = revenue / total if total else Decimal(0)
        without = recipe_from is None or recipe_from > end
        return {
            "module": "M7",
            "supported": True,
            "object": item.name,
            "restaurant": "Вся сеть",
            "period": ev["window"],
            "formula": "Доля = выручка блюда / выручка сети за окно; техкарта — строки ТТК блюда, "
            "действующие в окне",
            "steps": [
                {
                    "id": "sales",
                    "label": f"Продажи блюда за {first:%d.%m}–{end:%d.%m} по ресторанам",
                    "value": rub(revenue),
                    "unit": "",
                    "rows": [
                        {
                            "restaurant": codes.get(rid, "—"),
                            "portions": _q(q, Decimal(1)),
                            "amount": _q(r, Decimal("0.01")),
                        }
                        for rid, q, r in sorted(sales, key=lambda x: codes.get(x[0], ""))
                    ],
                }
            ],
            "result": [
                {"label": "Доля выручки сети", "value": pct(share), "unit": ""},
                {
                    "label": "Техкарта действует с",
                    "value": None if recipe_from is None else recipe_from.isoformat(),
                    "unit": "",
                },
            ],
            "rules": [
                {
                    "rule": "Блюдо продавалось в окне",
                    "value": str(len(sales)),
                    "threshold": "1",
                    "passed": bool(sales),
                },
                {
                    "rule": "Действующей техкарты нет",
                    "value": "нет" if without else "есть",
                    "threshold": "нет",
                    "passed": without,
                },
            ],
            "checks": [
                {
                    "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
                    "ok": abs(Decimal(ev["revenue_share"]) - share) < Decimal("0.0005"),
                    "note": f"движок: {pct(Decimal(ev['revenue_share']))}, пересчет: {pct(share)}",
                }
            ],
            "interpretation": [
                "Продукты блюда без техкарты списываются в расход, но ни одна техкарта их не объясняет — "
                "в M1 они выглядят как потери.",
                "Прежде чем подтверждать: проверьте, нет ли техкарты под другим названием блюда.",
            ],
        }
    model: type[Sale] | type[Receipt] = Sale if ev["source"] == "sales" else Receipt
    restaurant = session.get(Restaurant, f.restaurant_id)
    if restaurant is None:
        return {"module": "M7", "supported": False, "note": "Ресторана больше нет"}
    last = session.execute(
        select(func.max(model.day)).where(model.restaurant_id == restaurant.id)
    ).scalar_one_or_none()
    by_restaurant = session.execute(
        select(model.restaurant_id, func.max(model.day)).group_by(model.restaurant_id)
    ).all()
    network_last = max((d for _, d in by_restaurant), default=None)
    gap = (network_last - last).days if last and network_last else 0
    return {
        "module": "M7",
        "supported": True,
        "object": "Продажи" if ev["source"] == "sales" else "Закупки",
        "restaurant": restaurant.name,
        "period": [
            f.period_from.isoformat() if f.period_from else None,
            f.period_to.isoformat() if f.period_to else None,
        ],
        "formula": "Пауза = последний день с данными в сети − последний день с данными ресторана",
        "steps": [
            {
                "id": "last_days",
                "label": "Последний загруженный день по ресторанам",
                "value": None,
                "unit": "",
                "rows": [
                    {"restaurant": codes.get(rid, "—"), "day": d.isoformat()}
                    for rid, d in sorted(by_restaurant, key=lambda x: codes.get(x[0], ""))
                ],
            }
        ],
        "result": [{"label": "Дней без данных", "value": str(gap), "unit": ""}],
        "rules": [
            {
                "rule": "Данных нет дольше порога",
                "value": str(gap),
                "threshold": str(cfg.M7_GAP_DAYS),
                "passed": gap >= cfg.M7_GAP_DAYS,
            },
            {
                "rule": "Пауза длиннее обычной для ресторана",
                "value": f"{gap} дн.",
                "threshold": f"{cfg.M7_GAP_TIMES} × {ev['usual_pause_days']} дн.",
                "passed": gap > cfg.M7_GAP_TIMES * Decimal(ev["usual_pause_days"]),
            },
        ],
        "checks": [
            {
                "check": "Пересчет из исходных строк совпадает с тем, что посчитал движок",
                "ok": gap == ev["gap_days"],
                "note": f"движок: {ev['gap_days']} дн., пересчет: {gap} дн.",
            }
        ],
        "interpretation": [
            "Пока данных нет, модули не видят цены, приходы или продажи этих дней: находки по ресторану "
            "неполные.",
            "Если ресторан закрывался — отклоните находку с причиной «Не проблема».",
        ],
    }
