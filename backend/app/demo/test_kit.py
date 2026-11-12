"""The test kit for the stand (stage 8): Excel files shaped like real iiko, r_keeper and 1С:ERP exports, to
load by hand through the «Данные» screen into a separate network «Тестовая сеть».

The numbers come from the demo generator (3 restaurants, 9 weeks, its planted anomalies), so a person checks
the whole way a pilot will go: what the importer understood, names to match, errors by row, publishing,
freshness and the findings the engine makes of it. The files differ from the canonical templates the way
exports do: a title and a period above the table, other column names, real Excel dates and numbers, a totals
row, 1С names without codes and grams instead of kilograms. Two files carry deliberate mistakes to see the
error report.
Deterministic: the same seed gives the same bytes.
"""

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import xlsxwriter

from app.demo.generator import ERP_NAMES, generate
from app.imports.reader import read_table
from app.imports.templates import TEMPLATES

TEST_TENANT = "Тестовая сеть"
START = date(2026, 8, 17)  # a Monday; nine weeks up to the demo's last day of data
END = date(2026, 10, 18)
SEED = 7
RESTAURANTS = [
    ("R01", "Тестовый ресторан на Тверской", "Москва"),
    ("R02", "Тестовый ресторан на Арбате", "Москва"),
    ("R03", "Тестовый ресторан на Невском", "Санкт-Петербург"),
]
ERP_RESTAURANT = "R02"  # its purchases come from 1С:ERP by name only, with 1С's own names


@dataclass(frozen=True)
class Sheet:
    """How one export looks: its title, its columns (canonical header → the export's header and type)."""

    title: str
    columns: list[tuple[str, str, str]]  # (canonical header, export header, kind: text | number | date)
    totals: tuple[str, ...] = ()  # export headers summed in the «Итого» row


@dataclass
class Kit:
    files: dict[str, bytes] = field(default_factory=dict)  # path in the kit → bytes
    order: list[tuple[str, str | None]] = field(default_factory=list)  # (path, restaurant code or None)
    erp_names: dict[str, str] = field(default_factory=dict)  # 1С name → product code (the answer key)


T, N, D = "text", "number", "date"
REFERENCE: dict[str, tuple[str, Sheet]] = {
    "restaurants": (
        "01 Рестораны.xlsx",
        Sheet(
            "Подразделения сети",
            [("Код", "Код точки", T), ("Название", "Ресторан", T), ("Город", "Город", T)],
        ),
    ),
    "products": (
        "02 Номенклатура (iiko).xlsx",
        Sheet(
            "Номенклатура · iiko Office",
            [
                ("Код", "Артикул", T),
                ("Наименование", "Наименование", T),
                ("Категория", "Группа", T),
                ("Базовая ед.", "Ед. изм.", T),
                ("Срок годности, дней", "Срок годности", N),
                ("Тип", "Тип номенклатуры", T),
            ],
        ),
    ),
    "suppliers": (
        "03 Поставщики (1С).xlsx",
        Sheet(
            "Контрагенты · 1С:ERP",
            [("Код", "Код поставщика", T), ("Название", "Контрагент", T), ("ИНН", "ИНН", T)],
        ),
    ),
    "menu_items": (
        "04 Блюда (iiko).xlsx",
        Sheet(
            "Блюда меню · iiko Office",
            [
                ("Код", "Код блюда", T),
                ("Блюдо", "Наименование", T),
                ("Категория", "Раздел меню", T),
                ("Цена", "Цена продажи", N),
            ],
        ),
    ),
    "recipes": (
        "05 Техкарты (iiko).xlsx",
        Sheet(
            "Технологические карты · iiko Office",
            [
                ("Код блюда", "Код блюда/п/ф", T),
                ("Код товара", "Артикул", T),
                ("", "Ингредиент", T),  # filled from the products: iiko prints the name next to the code
                ("Брутто", "Кол-во брутто", N),
                ("Ед. изм.", "Ед.", T),
                ("Действует с", "Дата начала", D),
            ],
        ),
    ),
}
FACTS: dict[str, tuple[str, Sheet]] = {
    "sales": (
        "Продажи (r_keeper)",
        Sheet(
            "Продажи по блюдам · r_keeper",
            [
                ("Дата", "Дата", D),
                ("Код блюда", "Код блюда", T),
                ("Блюдо", "Наименование блюда", T),
                ("Количество", "Кол-во блюд", N),
                ("Выручка", "Сумма со скидкой", N),
                ("Скидка", "Сумма скидки", N),
                ("Кассир", "Официант", T),
            ],
            ("Кол-во блюд", "Сумма со скидкой", "Сумма скидки"),
        ),
    ),
    "receipts": (
        "Приходы (1С)",
        Sheet(
            "Поступление товаров и услуг · 1С:ERP",
            [
                ("Дата", "Дата документа", D),
                ("№ накладной", "Номер документа", T),
                ("Поставщик", "Контрагент", T),
                ("Товар", "Номенклатура", T),
                ("Количество", "Количество", N),
                ("Ед. изм.", "Ед. изм.", T),
                ("Цена", "Цена", N),
                ("Сумма", "Сумма с НДС", N),
                ("НДС", "Сумма НДС", N),
            ],
            ("Сумма с НДС", "Сумма НДС"),
        ),
    ),
    "write_offs": (
        "Списания (iiko)",
        Sheet(
            "Акты списания · iiko Office",
            [
                ("Дата", "Дата", D),
                ("Код товара", "Артикул", T),
                ("Товар", "Товар", T),
                ("Количество", "Количество", N),
                ("Ед. изм.", "Ед. изм.", T),
                ("Причина", "Статья списания", T),
            ],
        ),
    ),
    "inventory_counts": (
        "Инвентаризации (iiko)",
        Sheet(
            "Инвентаризация · iiko Office",
            [
                ("Дата", "Дата", D),
                ("Код товара", "Артикул", T),
                ("Товар", "Товар", T),
                ("Учетный остаток", "Остаток по учету", N),
                ("Фактический остаток", "Фактическое количество", N),
                ("Ед. изм.", "Ед. изм.", T),
            ],
        ),
    ),
    "stock_balances": (
        "Остатки на дату (iiko)",
        Sheet(
            "Остатки на дату · iiko Office",
            [
                ("Дата", "На дату", D),
                ("Код товара", "Артикул", T),
                ("Товар", "Товар", T),
                ("Остаток", "Конечный остаток", N),
                ("Ед. изм.", "Ед. изм.", T),
            ],
        ),
    ),
    "voids": (
        "Удаления (r_keeper)",
        Sheet(
            "Удаления и отмены · r_keeper",
            [
                ("Дата", "Дата", D),
                ("№ чека", "Номер чека", T),
                ("Код блюда", "Код блюда", T),
                ("Блюдо", "Позиция", T),
                ("Количество", "Кол-во", N),
                ("Сумма", "Сумма удаления", N),
                ("Кассир", "Кто удалил", T),
                ("После пречека", "После пречека", T),
                ("Причина", "Причина удаления", T),
            ],
            ("Сумма удаления",),
        ),
    ),
}
FACT_ORDER = ("sales", "receipts", "write_offs", "inventory_counts", "stock_balances", "voids")


def _table(raw: bytes, name: str) -> tuple[list[str], list[list[str]]]:
    """The generator's file as rows under the template's own column titles (its pretty XLSX too: a title
    above, totals below, other headers)."""
    template = TEMPLATES[name.rsplit("_", 1)[0] if "_R" in name else name.split(".")[0]]
    table = read_table(raw, name, template)
    header = [""] * (max(table.column_map.values()) + 1)
    for column, index in table.column_map.items():
        header[index] = template.column(column).title
    return header, [cells for _, cells in table.rows]


def _number(text: str) -> float | str | None:
    """A number as Excel keeps it; what is not a number stays text (a broken file keeps its mistake)."""
    cleaned = text.strip().replace(" ", "").replace(",", ".")
    try:
        return float(Decimal(cleaned)) if cleaned else None
    except ArithmeticError:
        return text


def _day(text: str) -> datetime:
    text = text.strip()
    return datetime.strptime(text[:10], "%Y-%m-%d" if "-" in text[:10] else "%d.%m.%Y")


def _xlsx(sheet: Sheet, rows: list[list[Any]], subtitle: str) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    wb.set_properties({"created": datetime(2026, 1, 1)})  # fixed metadata: the same seed gives the same bytes
    bold = wb.add_format({"bold": True})
    head = wb.add_format({"bold": True, "bg_color": "#E8EEF4", "border": 1, "text_wrap": True})
    day = wb.add_format({"num_format": "dd.mm.yyyy"})
    money = wb.add_format({"num_format": "# ##0.00"})
    qty = wb.add_format({"num_format": "0.###"})
    ws = wb.add_worksheet("Отчет")
    ws.write(0, 0, sheet.title, bold)
    ws.write(1, 0, subtitle)
    headers = [h for _, h, _ in sheet.columns]
    for j, h in enumerate(headers):
        ws.write(3, j, h, head)
        ws.set_column(j, j, max(12, min(40, len(h) + 4)))
    for i, row in enumerate(rows, start=4):
        for j, ((_, h, kind), v) in enumerate(zip(sheet.columns, row, strict=True)):
            if v is None or v == "":
                continue
            if kind == D:
                ws.write_datetime(i, j, v, day)
            elif kind == N and not isinstance(v, str):
                ws.write_number(i, j, v, money if h.startswith(("Сумма", "Цена")) else qty)
            else:
                ws.write_string(i, j, str(v))
    if sheet.totals:
        last = len(rows) + 4
        ws.write(last, 0, "Итого", bold)
        for j, h in enumerate(headers):
            if h in sheet.totals:
                total = sum(Decimal(str(r[j])) for r in rows if isinstance(r[j], float))
                ws.write_number(last, j, float(total), money)
    wb.close()
    return buf.getvalue()


def _shape(sheet: Sheet, header: list[str], body: list[list[str]], fill: dict[str, Any]) -> list[list[Any]]:
    out = []
    for cells in body:
        source = dict(zip(header, cells, strict=False))
        row: list[Any] = []
        for canonical, export, kind in sheet.columns:
            text = (
                source.get(canonical, "") if canonical else fill.get(export, {}).get(source.get("Код товара"))
            )
            text = "" if text is None else str(text)
            row.append(_day(text) if kind == D and text else _number(text) if kind == N else text)
        out.append(row)
    return out


def build(seed: int = SEED) -> Kit:
    net = generate(seed=seed, restaurants=len(RESTAURANTS), start=START, end=END)
    kit = Kit()
    period = f"Период: {START:%d.%m.%Y} – {END:%d.%m.%Y}"
    names = {code: name for code, name, _ in RESTAURANTS}
    _, products = _table(net.files["products.csv"], "products.csv")
    product_name = {r[0]: r[1] for r in products}

    for template, (path, sheet) in REFERENCE.items():
        if template == "restaurants":
            rows: list[list[Any]] = [list(r) for r in RESTAURANTS]
        else:
            header, body = _table(net.files[f"{template}.csv"], f"{template}.csv")
            if template == "products":  # iiko says «Товар» and «Заготовка»
                body = [[*r[:5], "Заготовка" if r[5] in ("п/ф", "полуфабрикат") else "Товар"] for r in body]
            rows = _shape(sheet, header, body, {"Ингредиент": product_name})
        kit.files[f"1 Справочники сети/{path}"] = _xlsx(sheet, rows, "Выгрузка справочника сети")
        kit.order.append((f"1 Справочники сети/{path}", None))

    for n, (code, name, _) in enumerate(RESTAURANTS, start=2):
        folder = f"{n} {code} {name.removeprefix('Тестовый ресторан ')}"
        for template in FACT_ORDER:
            title, sheet = FACTS[template]
            file = next(f for f in net.files if f.startswith(f"{template}_{code}."))
            header, body = _table(net.files[file], file)
            if template == "receipts":
                body = [_erp_row(header, r, kit) if code == ERP_RESTAURANT else r for r in body]
            rows = _shape(sheet, header, body, {})
            path = f"{folder}/{title} {code}.xlsx"
            kit.files[path] = _xlsx(sheet, rows, f"{names[code]} · {period}")
            kit.order.append((path, code))

    _broken(kit, net.files["sales_R02.csv"], "sales_R02.csv")
    return kit


def _erp_row(header: list[str], row: list[str], kit: Kit) -> list[str]:
    """1С:ERP knows the products by its own names, not by iiko codes: the importer asks to match them once."""
    source = dict(zip(header, row, strict=True))
    code = source["Код товара"]
    if code in ERP_NAMES:
        kit.erp_names[ERP_NAMES[code]] = code
        source["Товар"] = ERP_NAMES[code]
    source["Код товара"] = ""
    return [source[h] for h in header]


BROKEN = "9 Файлы с ошибками"


def _broken(kit: Kit, raw: bytes, name: str) -> None:
    """Two files to see the error report: wrong values in sales, an unknown unit in purchases."""
    title, sheet = FACTS["sales"]
    header, body = _table(raw, name)
    body = [list(r) for r in body[:60]]
    body[4][header.index("Количество")] = "-3"  # a negative quantity
    body[11][header.index("Дата")] = "31.12.2026"  # a date in the future
    body[25][header.index("Выручка")] = "много"  # not a number
    rows = _shape(sheet, header, body, {})
    kit.files[f"{BROKEN}/{title} R02 — с ошибками.xlsx"] = _xlsx(
        sheet, rows, "Три строки с ошибками: 9, 16, 30"
    )
    receipt_title, receipt = FACTS["receipts"]
    rows = [
        [
            datetime(2026, 10, 12),
            "ТЕСТ-0001",
            "Сырный дом",
            "Сыр Моцарелла",
            12.0,
            "упак",
            7440.0,
            7440.0,
            676.36,
        ],
        [datetime(2026, 10, 12), "ТЕСТ-0001", "Сырный дом", "Сыр Пармезан", 2.0, "кг", 3300.0, 6600.0, 600.0],
    ]
    kit.files[f"{BROKEN}/{receipt_title} R01 — неизвестная единица.xlsx"] = _xlsx(
        receipt,
        rows,
        "Единица «упак»: коэффициент не угадываем — задайте его в отчете о загрузке "
        "или в «Нормах и настройках»",
    )
