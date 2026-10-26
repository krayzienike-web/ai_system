"""Turning rows of a file into typed records, with a report a non-IT person can act on:
«строка 154: неизвестная единица «кг.» у товара «Сыр Моцарелла»». Pure functions, no database."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.imports.matching import normalize
from app.imports.reader import Table
from app.imports.templates import Kind, Template

MAX_ISSUES = 200
AMOUNT_TOLERANCE = Decimal("0.01")  # amount = price × qty ± 1%


@dataclass(frozen=True)
class Issue:
    row: int | None
    column: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "message": self.message}


@dataclass(frozen=True)
class Ref:
    id: UUID
    name: str
    base_unit: str | None = None
    is_semi: bool = False


@dataclass
class Lookups:
    """Reference data of the network: by code, by normalised name, and by remembered aliases
    (`code:<code>` or a normalised name from another system)."""

    products: dict[str, Ref] = field(default_factory=dict)
    product_names: dict[str, Ref] = field(default_factory=dict)
    menu_items: dict[str, Ref] = field(default_factory=dict)
    menu_item_names: dict[str, Ref] = field(default_factory=dict)
    suppliers: dict[str, Ref] = field(default_factory=dict)
    supplier_names: dict[str, Ref] = field(default_factory=dict)
    aliases: dict[tuple[str, str], Ref] = field(default_factory=dict)  # (kind, source_key) -> ref
    used: set[str] = field(default_factory=set)  # "kind:source_key" of aliases the file relied on
    # Transfers name other restaurants a director cannot see: the database resolves one name at a time.
    resolve_restaurant: Callable[[str], UUID | None] = lambda _text: None
    own_restaurant_id: UUID | None = None  # the restaurant the file is uploaded for
    # Write-off reason of the export → the network's reason code (norms); unknown ones become «other».
    classify_reason: Callable[[str | None], str] = lambda _text: "other"
    unknown_reasons: set[str] = field(default_factory=set)


@dataclass
class Unmatched:
    """A name the catalog does not know: to be matched by a person once."""

    kind: str  # product | menu_item | supplier
    code: str | None
    name: str | None
    rows: list[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        return source_key(self.code, self.name)


@dataclass
class Result:
    records: list[dict[str, Any]]
    errors: list[Issue]
    warnings: list[Issue]
    rows_total: int
    period_from: date | None = None
    period_to: date | None = None
    unmatched: list[Unmatched] = field(default_factory=list)
    skipped: int = 0  # incoming transfers: counted from the sender's export


class _RowError(Exception):
    def __init__(self, column: str | None, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


class _Skip(Exception):
    """A valid row that belongs to another file (an incoming transfer)."""


class _NotFound(Exception):
    def __init__(self, kind: str, code: str | None, name: str | None) -> None:
        super().__init__(kind)
        self.kind, self.code, self.name = kind, code, name


def source_key(code: str | None, name: str | None) -> str:
    """How a name from a file is remembered: by its normalised name, or by code when there is no name."""
    return normalize(name) if name else f"code:{code}"


# ------------------------------------------------------------------ values

UNITS = {
    "kg": ("kg", Decimal(1)),
    "кг": ("kg", Decimal(1)),
    "килограмм": ("kg", Decimal(1)),
    "g": ("kg", Decimal("0.001")),
    "г": ("kg", Decimal("0.001")),
    "гр": ("kg", Decimal("0.001")),
    "грамм": ("kg", Decimal("0.001")),
    "l": ("l", Decimal(1)),
    "л": ("l", Decimal(1)),
    "литр": ("l", Decimal(1)),
    "ml": ("l", Decimal("0.001")),
    "мл": ("l", Decimal("0.001")),
    "pcs": ("pcs", Decimal(1)),
    "шт": ("pcs", Decimal(1)),
    "штук": ("pcs", Decimal(1)),
}
UNIT_TITLES = {"kg": "кг", "l": "л", "pcs": "шт"}
SEMI_WORDS = {"п/ф", "пф", "полуфабрикат", "заготовка"}
GOODS_WORDS = {"", "товар", "сырье", "продукт"}


def unit_of(text: str) -> tuple[str, Decimal] | None:
    """«кг.», «Кг», «гр» → (base unit, factor). Unknown → None: never guess (domain invariant 4)."""
    return UNITS.get(text.strip().lower().rstrip("."))


def parse_decimal(text: str) -> Decimal:
    cleaned = re.sub(r"[\s\xa0₽]", "", text).replace(",", ".")
    if cleaned.count(".") > 1:  # "1.234.567,8" style thousands
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(text) from None
    if not value.is_finite():
        raise ValueError(text)
    return value


def parse_date(text: str) -> date:
    value = text.strip()
    for fmt in (
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d.%m.%y",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def _cell(cells: list[str], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def _values(template: Template, table: Table, cells: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in template.columns:
        raw = _cell(cells, table.column_map.get(column.name))
        if not raw:
            if column.required:
                raise _RowError(column.title, "пустое значение")
            out[column.name] = None
            continue
        try:
            if column.kind is Kind.DECIMAL:
                out[column.name] = parse_decimal(raw)
            elif column.kind is Kind.INT:
                out[column.name] = int(parse_decimal(raw))
            elif column.kind is Kind.DATE:
                out[column.name] = parse_date(raw)
            else:
                out[column.name] = raw
        except ValueError:
            kind = {"decimal": "число", "int": "целое число", "date": "дата (ДД.ММ.ГГГГ)"}[column.kind]
            raise _RowError(column.title, f"«{raw}» — ожидается {kind}") from None
    return out


# ------------------------------------------------------------------ references


def _resolve(
    kind: str,
    code: str | None,
    name: str | None,
    by_code: dict[str, Ref],
    by_name: dict[str, Ref],
    lk: Lookups,
) -> Ref:
    if code and code in by_code:
        return by_code[code]
    if name and normalize(name) in by_name:
        return by_name[normalize(name)]
    for key in (normalize(name) if name else None, f"code:{code}" if code else None):
        if key and (kind, key) in lk.aliases:
            lk.used.add(f"{kind}:{key}")
            return lk.aliases[(kind, key)]
    raise _NotFound(kind, code, name)


def _to_base(qty: Decimal, unit_text: str | None, product: Ref) -> Decimal:
    if not unit_text:
        return qty  # no unit column: the file is in base units
    unit = unit_of(unit_text)
    if unit is None:
        raise _RowError("Ед. изм.", f"неизвестная единица «{unit_text}» у товара «{product.name}»")
    base, factor = unit
    if base != product.base_unit:
        expected = UNIT_TITLES.get(product.base_unit or "", product.base_unit)
        raise _RowError(
            "Ед. изм.",
            f"«{unit_text}» не переводится в «{expected}» для товара «{product.name}»; нужен коэффициент",
        )
    return qty * factor


def _product(v: dict[str, Any], lk: Lookups) -> Ref:
    return _resolve(
        "product", v.get("product_code"), v.get("product_name"), lk.products, lk.product_names, lk
    )


# ------------------------------------------------------------------ records per template


def _record(template: str, v: dict[str, Any], lk: Lookups, warn: list[str]) -> dict[str, Any]:
    if template == "restaurants":
        return {"code": v["code"], "name": v["name"], "city": v["city"]}
    if template == "products":
        kind = (v["kind"] or "").strip().lower().rstrip(".")
        if kind not in SEMI_WORDS | GOODS_WORDS:
            raise _RowError("Тип", f"«{v['kind']}» — укажите «товар» или «полуфабрикат»")
        unit = unit_of(v["unit"])
        if unit is None or unit[1] != 1:
            raise _RowError("Базовая ед.", f"«{v['unit']}» — базовая единица должна быть кг, л или шт")
        return {
            "code": v["code"],
            "name": v["name"],
            "category": v["category"],
            "base_unit": unit[0],
            "shelf_life_days": v["shelf_life_days"],
            "is_semi": kind in SEMI_WORDS,
        }
    if template == "suppliers":
        inn = v["inn"]
        if inn and not re.fullmatch(r"\d{10}|\d{12}", inn):
            raise _RowError("ИНН", f"«{inn}» — ИНН состоит из 10 или 12 цифр")
        return {"code": v["code"], "name": v["name"], "inn": inn}
    if template == "menu_items":
        return {"code": v["code"], "name": v["name"], "category": v["category"], "price": v["price"]}
    if template == "recipes":
        parent_code = v["menu_item_code"]
        parent: dict[str, UUID | None] = {"menu_item_id": None, "semi_product_id": None}
        semi = lk.products.get(parent_code)
        if parent_code not in lk.menu_items and semi is not None:
            if not semi.is_semi:
                raise _RowError(
                    "Код блюда",
                    f"«{semi.name}» — товар, а не полуфабрикат: отметьте его в номенклатуре (Тип: п/ф)",
                )
            parent["semi_product_id"] = semi.id
        else:
            parent["menu_item_id"] = _resolve(
                "menu_item", parent_code, None, lk.menu_items, lk.menu_item_names, lk
            ).id
        product = _product(v, lk)
        qty = _to_base(v["gross_qty"], v["unit"], product)
        if qty <= 0:
            raise _RowError("Брутто", "количество должно быть больше нуля")
        return {
            **parent,
            "product_id": product.id,
            "gross_qty": qty,
            "valid_from": v["valid_from"],
        }
    if template == "sales":
        item = _resolve(
            "menu_item", v["menu_item_code"], v["menu_item_name"], lk.menu_items, lk.menu_item_names, lk
        )
        if v["qty"] < 0:
            raise _RowError(
                "Количество",
                "отрицательное количество: возвраты в продажах пока не поддерживаются",
            )
        return {
            "day": v["day"],
            "menu_item_id": item.id,
            "qty": v["qty"],
            "revenue": v["revenue"],
            "discount": v["discount"] or Decimal(0),
        }
    if template == "name_sync":
        # Several names of 1С:ERP (one per supplier) become one product of iiko: network-wide matches.
        product = _product(v, lk)
        return {
            "kind": "product",
            "source_key": source_key(v["erp_code"], v["erp_name"]),
            "source_text": v["erp_name"] or v["erp_code"],
            "target_id": product.id,
        }
    if template == "contract_prices":
        product = _product(v, lk)
        vendor = _resolve(
            "supplier", v["supplier_code"], v["supplier_name"], lk.suppliers, lk.supplier_names, lk
        )
        per_unit = _to_base(Decimal(1), v["unit"], product)  # how many base units one price unit is
        if v["price"] <= 0:
            raise _RowError("Цена по договору", "цена должна быть больше нуля")
        if v["valid_to"] is not None and v["valid_to"] < v["valid_from"]:
            raise _RowError("Действует по", "дата окончания раньше даты начала")
        return {
            "supplier_id": vendor.id,
            "product_id": product.id,
            "price": v["price"] / per_unit,
            "valid_from": v["valid_from"],
            "valid_to": v["valid_to"],
        }
    if template == "receipts":
        product = _product(v, lk)
        supplier = None
        if v["supplier_code"] or v["supplier_name"]:
            supplier = _resolve(
                "supplier", v["supplier_code"], v["supplier_name"], lk.suppliers, lk.supplier_names, lk
            )
        qty = _to_base(v["qty"], v["unit"], product)
        if qty <= 0:
            raise _RowError("Количество", "количество в накладной должно быть больше нуля")
        if v["price"] is not None and v["qty"]:
            expected = v["price"] * v["qty"]
            if expected and abs(v["amount"] - expected) > abs(expected) * AMOUNT_TOLERANCE:
                warn.append(f"сумма {v['amount']} не равна цене × количество ({expected:.2f})")
        return {
            "day": v["day"],
            "doc_no": v["doc_no"],
            "supplier_id": supplier.id if supplier else None,
            "product_id": product.id,
            "qty": qty,
            "amount": v["amount"],
            "vat": v["vat"],
        }
    if template == "transfers":
        sender = lk.resolve_restaurant(v["from_restaurant"])
        receiver = lk.resolve_restaurant(v["to_restaurant"])
        if sender is None:
            raise _RowError("Откуда", f"неизвестный ресторан «{v['from_restaurant']}»")
        if receiver is None:
            raise _RowError("Куда", f"неизвестный ресторан «{v['to_restaurant']}»")
        if sender == receiver:
            raise _RowError("Куда", "перемещение в тот же ресторан")
        if sender != lk.own_restaurant_id:
            raise _Skip
        product = _product(v, lk)
        qty = _to_base(v["qty"], v["unit"], product)
        if qty <= 0:
            raise _RowError("Количество", "количество должно быть больше нуля")
        return {"day": v["day"], "to_restaurant_id": receiver, "product_id": product.id, "qty": qty}
    if template == "write_offs":
        product = _product(v, lk)
        qty = _to_base(v["qty"], v["unit"], product)
        if qty <= 0:
            raise _RowError("Количество", "количество списания должно быть больше нуля")
        code = lk.classify_reason(v["reason"])
        if code == "other" and v["reason"]:
            lk.unknown_reasons.add(str(v["reason"]).strip())
        return {
            "day": v["day"],
            "product_id": product.id,
            "qty": qty,
            "reason": v["reason"],
            "reason_code": code,
        }
    if template == "inventory_counts":
        product = _product(v, lk)
        actual = _to_base(v["actual_qty"], v["unit"], product)
        if actual < 0:
            raise _RowError("Фактический остаток", "остаток не может быть отрицательным")
        book = _to_base(v["book_qty"], v["unit"], product) if v["book_qty"] is not None else None
        return {"day": v["day"], "product_id": product.id, "book_qty": book, "actual_qty": actual}
    raise ValueError(template)


def validate(template: Template, table: Table, lookups: Lookups, *, today: date) -> Result:
    records: list[dict[str, Any]] = []
    errors: list[Issue] = []
    warnings: list[Issue] = []
    unmatched: dict[tuple[str, str], Unmatched] = {}
    waiting_days: list[date] = []  # dates of rows that wait for a name match: still part of the file's period
    skipped = 0
    for number, cells in table.rows:
        warn: list[str] = []
        try:
            values = _values(template, table, cells)
            record = _record(template.name, values, lookups, warn)
        except _RowError as e:
            errors.append(Issue(number, e.column, e.message))
            continue
        except _Skip:
            skipped += 1
            continue
        except _NotFound as e:
            item = unmatched.setdefault(
                (e.kind, source_key(e.code, e.name)), Unmatched(e.kind, e.code, e.name)
            )
            item.rows.append(number)
            if isinstance(values.get("day"), date):
                waiting_days.append(values["day"])
            continue
        day = record.get("day")
        if isinstance(day, date) and day > today:
            errors.append(Issue(number, "Дата", f"дата {day:%d.%m.%Y} в будущем"))
            continue
        warnings.extend(Issue(number, None, w) for w in warn)
        records.append(record)
    if skipped:
        warnings.append(
            Issue(
                None,
                None,
                f"входящих перемещений: {skipped} — их учитываем по выгрузке ресторана-отправителя",
            )
        )
    if table.skipped_totals:
        warnings.append(Issue(None, None, f"пропущено строк итогов: {table.skipped_totals}"))
    if lookups.unknown_reasons:
        names = ", ".join(f"«{r}»" for r in sorted(lookups.unknown_reasons)[:5])
        more = len(lookups.unknown_reasons) - 5
        warnings.append(
            Issue(
                None,
                "Причина",
                f"причины не из справочника, учтены как «Прочее»: {names}"
                + (f" и еще {more}" if more > 0 else "")
                + ". Добавьте их в «Нормы и настройки»",
            )
        )
    if table.unmapped:
        warnings.append(Issue(None, None, "колонки не используются: " + ", ".join(table.unmapped)))
    days = [r["day"] for r in records if "day" in r] + waiting_days
    result = Result(
        records,
        errors,
        warnings,
        rows_total=len(table.rows),
        unmatched=list(unmatched.values()),
        skipped=skipped,
    )
    if days:
        result.period_from, result.period_to = min(days), max(days)
    if len(errors) > MAX_ISSUES:
        hidden = len(errors) - MAX_ISSUES
        result.errors = [*errors[:MAX_ISSUES], Issue(None, None, f"и еще {hidden} ошибок того же рода")]
    return result
