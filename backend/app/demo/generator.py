"""Synthetic demo network: 12 restaurants, 6 months, with planted anomalies (roadmap stage 2).

Produces the files a network would export (canonical templates, some in "real" shapes: a pretty XLSX
with a title and totals, cp1251, grams instead of kilograms) plus `anomalies.json` — the ground truth the
analytics detectors (stage 3) are measured against. Deterministic: the same seed gives the same bytes.

Physics of the simulation, per restaurant × product × day:
- theoretical usage = Σ dishes sold × recipe gross quantity;
- real usage = theoretical × (1 + normal loss) × planted anomalies;
- the books (iiko) move by theory, the shelf moves by reality; a stock count shows both and resets the books.
"""

import csv
import io
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import xlsxwriter

START = date(2026, 4, 20)
END = date(2026, 10, 18)
COUNT_DAYS = (
    date(2026, 6, 1),
    date(2026, 8, 3),
    date(2026, 10, 1),
)  # full stock counts after the opening one

RESTAURANTS = [
    ("R01", "Ресторан на Тверской", "Москва", 1.3),
    ("R02", "Ресторан на Арбате", "Москва", 1.1),
    ("R03", "Ресторан на Невском", "Санкт-Петербург", 1.0),
    ("R04", "Ресторан на Покровке", "Москва", 0.9),
    ("R05", "Ресторан на Патриарших", "Москва", 1.2),
    ("R06", "Ресторан на Кутузовском", "Москва", 1.0),
    ("R07", "Ресторан на Баумана", "Казань", 0.8),
    ("R08", "Ресторан на Вайнера", "Екатеринбург", 0.8),
    ("R09", "Ресторан на Красном проспекте", "Новосибирск", 0.7),
    ("R10", "Ресторан на Курортном", "Сочи", 0.9),
    ("R11", "Ресторан на Большой Покровской", "Нижний Новгород", 0.7),
    ("R12", "Ресторан на Красной", "Краснодар", 0.8),
]

# code, name, category, unit, shelf life (days), base price ₽ per unit, supplier, normal loss
PRODUCTS = [
    ("P01", "Сыр Моцарелла", "Сыры", "kg", 10, 620, "S1", 0.02),
    ("P02", "Сыр Пармезан", "Сыры", "kg", 60, 1650, "S1", 0.01),
    ("P03", "Сыр Грана Падано", "Сыры", "kg", 60, 1480, "S1", 0.01),
    ("P04", "Сливки 33%", "Молочные", "l", 7, 360, "S3", 0.015),
    ("P05", "Мука пшеничная", "Бакалея", "kg", 180, 48, "S7", 0.01),
    ("P06", "Томаты", "Овощи", "kg", 6, 210, "S4", 0.03),
    ("P07", "Куриное филе", "Мясо и птица", "kg", 5, 330, "S2", 0.02),
    ("P08", "Говядина вырезка", "Мясо и птица", "kg", 5, 1020, "S2", 0.02),
    ("P09", "Лосось охлажденный", "Рыба", "kg", 4, 1450, "S5", 0.02),
    ("P10", "Руккола", "Зелень", "kg", 3, 900, "S4", 0.03),
    ("P11", "Картофель фри замороженный", "Заморозка", "kg", 180, 160, "S7", 0.015),
    ("P12", "Хлеб чиабатта", "Хлеб", "pcs", 2, 45, "S6", 0.0),
    ("P13", "Яйцо куриное", "Молочные", "pcs", 21, 11, "S3", 0.01),
    ("P14", "Масло оливковое", "Бакалея", "l", 365, 1100, "S7", 0.01),
    ("P15", "Паста спагетти", "Бакалея", "kg", 365, 190, "S7", 0.005),
    ("P16", "Салат романо", "Зелень", "kg", 5, 520, "S4", 0.03),
]
PRODUCT = {p[0]: p for p in PRODUCTS}

SUPPLIERS = [
    ("S1", "Сырный дом", "7701234567", (1, 4)),  # delivery weekdays: Monday = 0
    ("S2", "Мясной ряд", "7702345678", (0, 2, 4)),
    ("S3", "Молочный двор", "7703456789", (0, 3)),
    ("S4", "Зелень Экспресс", "7704567890", (0, 2, 4)),
    ("S5", "Северная рыба", "7805678901", (1, 4)),
    ("S6", "Пекарня №1", "7706789012", (0, 1, 2, 3, 4, 5, 6)),
    ("S7", "Бакалея Опт", "7707890123", (2,)),
    ("S8", "Мясной экспресс", "7708901234", (0, 1, 2, 3, 4, 5)),  # expensive urgent supplier
]
SUPPLIER = {s[0]: s for s in SUPPLIERS}

# code, name, category, price ₽, daily base sales, recipe {product: gross per portion in base unit}
MENU = [
    ("M01", "Пицца Маргарита", "Пицца", 580, 34, {"P01": 0.14, "P05": 0.18, "P17": 0.08, "P14": 0.01}),
    ("M02", "Пицца Четыре сыра", "Пицца", 760, 16, {"P01": 0.10, "P02": 0.03, "P03": 0.03, "P05": 0.18}),
    ("M03", "Паста Карбонара", "Паста", 640, 22, {"P15": 0.12, "P04": 0.08, "P13": 2, "P02": 0.02}),
    ("M04", "Паста с лососем", "Паста", 890, 12, {"P15": 0.12, "P09": 0.09, "P04": 0.07}),
    (
        "M05",
        "Салат Цезарь с курицей",
        "Салаты",
        590,
        26,
        {"P07": 0.10, "P16": 0.08, "P03": 0.015, "P12": 0.5},
    ),
    ("M06", "Стейк из говядины", "Горячее", 1490, 9, {"P08": 0.24, "P14": 0.01}),
    ("M07", "Лосось на гриле", "Горячее", 1390, 8, {"P09": 0.20, "P10": 0.03, "P14": 0.01}),
    ("M08", "Картофель фри", "Закуски", 290, 30, {"P11": 0.17}),
    ("M09", "Брускетта с томатами", "Закуски", 390, 14, {"P12": 1, "P06": 0.06, "P14": 0.01}),
    ("M10", "Салат с рукколой", "Салаты", 520, 13, {"P10": 0.06, "P06": 0.05, "P02": 0.015}),
    ("M11", "Куриные котлеты", "Горячее", 610, 11, {"P07": 0.18, "P13": 1, "P12": 0.5}),
    ("M12", "Тыквенный суп", "Супы", 420, 10, {}),  # seasonal, no recipe: the system cannot see its losses
]
SEASONAL_FROM = date(2026, 9, 1)
VAT = {
    "Хлеб": Decimal("0.10"),
    "Молочные": Decimal("0.10"),
    "Овощи": Decimal("0.10"),
    "Зелень": Decimal("0.10"),
}
# Semi-finished products: made in the kitchen from raw products, per 1 base unit. Not stocked in the demo.
SEMI = {"P17": ("Соус томатный (п/ф)", "Заготовки", "kg", 2, {"P06": 1.25, "P14": 0.03})}
# Goods moved between restaurants: every Monday R05 sends R06 flour (sender, receiver, product, qty).
TRANSFERS = [("R05", "R06", "P05", 5.0)]

PERISHABLE_WRITE_OFF = {"P10": 0.05, "P16": 0.04, "P06": 0.02, "P04": 0.01, "P12": 0.04}


@dataclass
class DemoNetwork:
    files: dict[str, bytes] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    # Names from another system and what they are: the answer key for name matching.
    name_matches: dict[str, str] = field(default_factory=dict)  # source name -> product code


# How 1С names some products in R04's purchases (no codes): the importer must ask to match them once.
ERP_NAMES = {
    "P01": "Моцарелла фиор ди латте 45%",
    "P07": "Филе куриное охл.",
    "P10": "Руккола свежая, кг",
    "P14": "Масло оливк. Extra Virgin",
    "P09": "Лосось атлантический охл. (филе)",
}


def _q(value: float, places: str = "0.001") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _csv(
    header: list[str], rows: list[list[Any]], encoding: str = "utf-8-sig", delimiter: str = ";"
) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode(encoding)


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, Decimal):
        return format(v, "f").replace(".", ",")
    return str(v)


def _pretty_xlsx(title: str, header: list[str], rows: list[list[Any]], totals: list[Any]) -> bytes:
    """An export as people get it from r_keeper: a title, an empty line, the table and a totals row."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    wb.set_properties({"created": datetime(2026, 1, 1)})  # fixed metadata: the same seed gives the same bytes
    ws = wb.add_worksheet("Продажи")
    ws.write(0, 0, title)
    for j, h in enumerate(header):
        ws.write(2, j, h)
    for i, row in enumerate(rows, start=3):
        for j, v in enumerate(row):
            ws.write(i, j, _fmt(v) if isinstance(v, date) else float(v) if isinstance(v, Decimal) else v)
    for j, v in enumerate(totals):
        ws.write(len(rows) + 3, j, float(v) if isinstance(v, Decimal) else v)
    wb.close()
    return buf.getvalue()


def _period_of(day: date) -> int:
    """0 before the first count, 1 between the first and the second, …"""
    return sum(1 for c in COUNT_DAYS if day > c)


def generate(seed: int = 42, restaurants: int = 12, start: date = START, end: date = END) -> DemoNetwork:
    rnd = random.Random(seed)  # noqa: S311  (a simulation, not security)
    net = DemoNetwork()
    chosen = RESTAURANTS[:restaurants]
    codes = [r[0] for r in chosen]
    count_days = [d for d in COUNT_DAYS if start < d <= end]

    # ------------------------------------------------------------ planted anomalies (ground truth)
    def planted(**a: Any) -> None:
        if a.get("restaurant") in (None, *codes):
            net.anomalies.append(a)

    planted(
        id="r01-mozzarella-overuse",
        restaurant="R01",
        module="M1",
        product="P01",
        kind="problem",
        description="Перерасход моцареллы растет от периода к периоду: +4% → +6,5% → +9% сверх нормы",
        overuse_by_period=[0.04, 0.065, 0.09, 0.09],
    )
    planted(
        id="r03-salmon-yield",
        restaurant="R03",
        module="M1",
        product="P09",
        kind="problem",
        description="Лосось: выход при разделке ниже ТТК, перерасход +6,8% весь период",
        overuse_by_period=[0.068] * 4,
    )
    planted(
        id="net-fries-recipe",
        restaurant=None,
        module="M1",
        product="P11",
        kind="problem",
        description="Картофель фри: ТТК устарела — во всех ресторанах одинаковый перерасход +6,2%",
        overuse_by_period=[0.062] * 4,
    )
    planted(
        id="r02-beef-urgent-orders",
        restaurant="R02",
        module="M3",
        product="P08",
        kind="problem",
        description="С 27.07 говядина закупается срочно у «Мясной экспресс» на 11% дороже",
        since="2026-07-27",
        price_premium=0.11,
        supplier="S8",
    )
    planted(
        id="r05-cream-price",
        restaurant="R05",
        module="M3",
        product="P04",
        kind="problem",
        description="С 01.08 сливки у «Молочный двор» на 14% дороже, чем другим ресторанам",
        since="2026-08-01",
        price_premium=0.14,
        supplier="S3",
    )
    planted(
        id="net-salmon-price",
        restaurant=None,
        module="M2",
        product="P09",
        menu_item="M07",
        kind="opportunity",
        description="С 01.09 лосось подорожал у поставщика на 40% для всей сети, а цена «Лосося на гриле» "
        "в меню прежняя — фудкост блюда выше целевого",
        since="2026-09-01",
        price_premium=0.40,
    )
    planted(
        id="r01-greens-write-offs",
        restaurant="R01",
        module="M5",
        product="P10",
        kind="problem",
        description="Руккола: списания в 3,3 раза выше сети — заказывают на 5–6 дней при сроке 3 дня",
        write_off_factor=3.3,
    )
    planted(
        id="r01-pre-count-write-offs",
        restaurant="R01",
        module="M4",
        kind="problem",
        description="Больше половины списаний оформляется за 2 дня до инвентаризации — закрытие недостач",
    )
    planted(
        id="r07-bread-weekdays",
        restaurant="R07",
        module="M5",
        product="P12",
        kind="problem",
        description="Хлеб заказывают одинаково на все дни, а в пн и вт продажи ниже — остаток списывают",
    )
    planted(
        id="r09-receipts-gap",
        restaurant="R09",
        module="M7",
        kind="data_quality",
        description="Закупки не выгружены за последние 7 дней — цены и приходы за неделю не проверены",
    )
    planted(
        id="r11-mis-sort",
        restaurant="R11",
        module="M4",
        product="P02",
        kind="problem",
        description="Последний пересчет: пармезан и грана перепутаны, излишек одного ≈ недостача другого",
    )
    planted(
        id="net-no-recipe",
        restaurant=None,
        module="M7",
        menu_item="M12",
        kind="data_quality",
        description="«Тыквенный суп» продается с 01.09 без ТТК — его расход система не видит",
    )

    overuse: dict[tuple[str, str], list[float]] = {}
    for a in net.anomalies:
        if "overuse_by_period" in a:
            for code in [a["restaurant"]] if a["restaurant"] else codes:
                overuse[(code, a["product"])] = a["overuse_by_period"]

    # ------------------------------------------------------------ reference data
    net.files["restaurants.csv"] = _csv(
        ["Код", "Название", "Город"], [[c, n, city] for c, n, city, _ in chosen]
    )
    unit_title = {"kg": "кг", "l": "л", "pcs": "шт"}
    net.files["products.csv"] = _csv(
        ["Код", "Наименование", "Категория", "Базовая ед.", "Срок годности, дней", "Тип"],
        [[p[0], p[1], p[2], unit_title[p[3]], p[4], "товар"] for p in PRODUCTS]
        + [[code, s[0], s[1], unit_title[s[2]], s[3], "п/ф"] for code, s in SEMI.items()],
    )
    net.files["suppliers.csv"] = _csv(["Код", "Название", "ИНН"], [[s[0], s[1], s[2]] for s in SUPPLIERS])
    net.files["menu_items.csv"] = _csv(
        ["Код", "Блюдо", "Категория", "Цена"], [[m[0], m[1], m[2], Decimal(m[3])] for m in MENU]
    )
    net.files["recipes.csv"] = _csv(
        ["Код блюда", "Код товара", "Брутто", "Ед. изм.", "Действует с"],
        [
            [m[0], p, _q(g), unit_title[(PRODUCT[p][3] if p in PRODUCT else SEMI[p][2])], date(2026, 1, 1)]
            for m in MENU
            for p, g in m[5].items()
        ]
        + [
            [code, p, _q(g), unit_title[PRODUCT[p][3]], date(2026, 1, 1)]
            for code, s in SEMI.items()
            for p, g in s[4].items()
        ],
    )

    # Transfers: the same goods leave one shelf and arrive on another.
    moves: dict[tuple[str, str, date], float] = defaultdict(float)
    transfer_rows: list[list[Any]] = []
    for sender, receiver, p_code, qty in TRANSFERS:
        if sender in codes and receiver in codes:
            for day in _days(start, end):
                if day.weekday() == 0:
                    moves[(sender, p_code, day)] -= qty
                    moves[(receiver, p_code, day)] += qty
                    transfer_rows.append(
                        [
                            day,
                            sender,
                            receiver,
                            p_code,
                            PRODUCT[p_code][1],
                            _q(qty),
                            unit_title[PRODUCT[p_code][3]],
                        ]
                    )

    # ------------------------------------------------------------ restaurants
    for code, name, _city, size in chosen:
        sales_rows: list[list[Any]] = []
        receipts_rows: list[list[Any]] = []
        write_off_rows: list[list[Any]] = []
        count_rows: list[list[Any]] = []
        days = _days(start, end)
        usage_theory: dict[str, dict[date, float]] = defaultdict(dict)

        for day in days:
            weekday = day.weekday()
            demand = {0: 0.8, 1: 0.82, 2: 0.95, 3: 1.0, 4: 1.25, 5: 1.35, 6: 1.15}[weekday]
            for m_code, m_name, _cat, price, base, recipe in MENU:
                if m_code == "M12" and day < SEASONAL_FROM:
                    continue
                qty = max(0, round(base * size * demand * rnd.gauss(1, 0.12)))
                if qty == 0:
                    continue
                gross = Decimal(qty * price)
                discount = _q(float(gross) * rnd.choice((0, 0, 0.03, 0.05)), "0.01")
                sales_rows.append([day, m_code, m_name, qty, gross - discount, discount])
                for p, g in recipe.items():
                    # A semi-finished product is used up as its raw products.
                    for raw, share in SEMI[p][4].items() if p in SEMI else ((p, 1.0),):
                        usage_theory[raw][day] = usage_theory[raw].get(day, 0) + qty * g * share

        # Stock simulation per product: the shelf (real) and the books (theory).
        for p_code, p_name, category, unit, _shelf, base_price, supplier, loss in PRODUCTS:
            theory = usage_theory.get(p_code, {})
            avg = sum(theory.values()) / max(len(days), 1)
            if avg == 0:
                continue
            deliveries = SUPPLIER[supplier][3]
            shelf_stock = book_stock = avg * 3
            # The opening count is taken the evening before the first day, like every count (end of day).
            opening = start - timedelta(days=1)
            count_rows.append([opening, p_code, p_name, _q(book_stock), _q(shelf_stock), unit_title[unit]])
            doc = 0
            pending_write_off = 0.0
            for day in days:
                t_use = theory.get(day, 0.0)
                factor = overuse.get((code, p_code), [0.0] * 4)[_period_of(day)]
                real = t_use * (1 + loss + factor) * rnd.gauss(1, 0.02)

                # Deliveries: cover the days until the next delivery plus a buffer.
                if day.weekday() in deliveries:
                    gap = min((d - day.weekday()) % 7 or 7 for d in deliveries)
                    horizon: float = gap + 1.5
                    if code == "R01" and p_code == "P10":
                        horizon = 6.0  # greens ordered for 5–6 days while they keep 3
                    if code == "R07" and p_code == "P12":
                        horizon = 1.0  # bread: the same order every day
                        need = avg * 1.15
                    else:
                        need = avg * horizon * 1.1 - shelf_stock
                    if need > 0:
                        delivered = _q(need) if unit != "pcs" else _q(round(need), "1")
                        sup, unit_price = supplier, base_price * (1 + rnd.uniform(-0.02, 0.02))
                        if code == "R02" and p_code == "P08" and day >= date(2026, 7, 27):
                            sup, unit_price = "S8", base_price * 1.11
                        if code == "R05" and p_code == "P04" and day >= date(2026, 8, 1):
                            unit_price = base_price * 1.14
                        if p_code == "P09" and day >= date(2026, 9, 1):
                            unit_price *= 1.40  # the market moved: the whole network pays more
                        doc += 1
                        amount = _q(float(delivered) * unit_price, "0.01")
                        vat_rate = VAT.get(category, Decimal("0.20"))
                        vat = _q(float(amount * vat_rate / (1 + vat_rate)), "0.01")
                        hidden = code == "R09" and day > end - timedelta(days=7)
                        if not hidden:
                            receipts_rows.append(
                                [
                                    day,
                                    f"{code}-{supplier}-{doc:04d}",
                                    sup,
                                    SUPPLIER[sup][1],
                                    p_code,
                                    p_name,
                                    delivered,
                                    unit_title[unit],
                                    _q(unit_price, "0.01"),
                                    amount,
                                    vat,
                                ]
                            )
                        shelf_stock += float(delivered)
                        book_stock += float(delivered)

                shelf_stock -= real
                book_stock -= t_use
                moved = moves.get((code, p_code, day), 0.0)
                shelf_stock += moved
                book_stock += moved

                # Write-offs: perishables spoil; some restaurants have planted habits.
                rate = PERISHABLE_WRITE_OFF.get(p_code, 0.0)
                if code == "R01" and p_code == "P10":
                    rate *= 3.3
                if code == "R07" and p_code == "P12" and day.weekday() in (0, 1):
                    rate = 0.25
                spoiled = min(max(shelf_stock, 0.0), avg * rate * rnd.uniform(0.5, 1.5))
                if code == "R01":
                    # Closing shortages: half of the spoilage is written off right before a count.
                    pending_write_off += spoiled * 0.6
                    spoiled *= 0.4
                    if any(0 < (c - day).days <= 2 for c in count_days) and pending_write_off > 0:
                        spoiled += pending_write_off
                        pending_write_off = 0.0
                if spoiled > 0.0005:
                    q = _q(spoiled) if unit != "pcs" else _q(max(1, round(spoiled)), "1")
                    write_off_rows.append([day, p_code, p_name, q, unit_title[unit], "Порча"])
                    shelf_stock -= float(q)
                    book_stock -= float(q)

                if shelf_stock < 0:
                    shelf_stock = book_stock = 0.0  # emergency purchase; not part of the story

                if day in count_days:
                    actual = shelf_stock
                    if code == "R11" and day == count_days[-1] and p_code in ("P02", "P03"):
                        swap = 0.6 if p_code == "P02" else -0.6  # counted under the wrong name
                        actual = max(0.0, shelf_stock + swap)
                    count_rows.append([day, p_code, p_name, _q(book_stock), _q(actual), unit_title[unit]])
                    book_stock = shelf_stock = actual

        # Shapes vary on purpose: the importer must adapt.
        if code == "R01":
            total_qty = sum(r[3] for r in sales_rows)
            total_rev = sum((r[4] for r in sales_rows), Decimal(0))
            net.files[f"sales_{code}.xlsx"] = _pretty_xlsx(
                f"Продажи блюд · {name} · {start:%d.%m.%Y}–{end:%d.%m.%Y}",
                ["Дата", "Код", "Блюдо", "Кол-во", "Сумма", "Скидка"],
                sales_rows,
                ["Итого", "", "", total_qty, total_rev, ""],
            )
        else:
            net.files[f"sales_{code}.csv"] = _csv(
                ["Дата", "Код блюда", "Блюдо", "Количество", "Выручка", "Скидка"], sales_rows
            )
        receipts_header = [
            "Дата",
            "№ накладной",
            "Код поставщика",
            "Поставщик",
            "Код товара",
            "Товар",
            "Количество",
            "Ед. изм.",
            "Цена",
            "Сумма",
            "НДС",
        ]
        if code == "R02":
            # 1С-style: cheese in grams, Windows-1251.
            for row in receipts_rows:
                if row[7] == "кг" and row[4] in ("P01", "P02", "P03"):
                    row[6], row[7], row[8] = (
                        _q(float(row[6]) * 1000, "1"),
                        "г",
                        _q(float(row[8]) / 1000, "0.0001"),
                    )
            net.files[f"receipts_{code}.csv"] = _csv(receipts_header, receipts_rows, encoding="cp1251")
        elif code == "R04":
            # 1С without codes and with its own names for some products.
            for row in receipts_rows:
                if row[4] in ERP_NAMES:
                    row[5] = ERP_NAMES[row[4]]
                    net.name_matches[row[5]] = row[4]
                row[4] = ""
            net.files[f"receipts_{code}.csv"] = _csv(receipts_header, receipts_rows)
        else:
            net.files[f"receipts_{code}.csv"] = _csv(receipts_header, receipts_rows)
        net.files[f"write_offs_{code}.csv"] = _csv(
            ["Дата", "Код товара", "Товар", "Количество", "Ед. изм.", "Причина"], write_off_rows
        )
        # Both sides export their transfers: the sender's file counts, the receiver's shows them as incoming.
        own_moves = [r for r in transfer_rows if code in (r[1], r[2])]
        if own_moves:
            net.files[f"transfers_{code}.csv"] = _csv(
                ["Дата", "Откуда", "Куда", "Код товара", "Товар", "Количество", "Ед. изм."], own_moves
            )
        net.files[f"inventory_counts_{code}.csv"] = _csv(
            ["Дата", "Код товара", "Товар", "Учетный остаток", "Фактический остаток", "Ед. изм."], count_rows
        )

    net.files["anomalies.json"] = json.dumps(
        {
            "seed": seed,
            "period": [start.isoformat(), end.isoformat()],
            "count_days": [d.isoformat() for d in count_days],
            "anomalies": net.anomalies,
            "name_matches": net.name_matches,
        },
        ensure_ascii=False,
        indent=2,
    ).encode()
    return net


# Order in which the files are loaded: reference data first, then each restaurant's facts.
REFERENCE_ORDER = ("restaurants", "products", "suppliers", "menu_items", "recipes")
FACT_ORDER = ("sales", "receipts", "transfers", "write_offs", "inventory_counts")


def load_plan(net: DemoNetwork) -> list[tuple[str, str | None, str]]:
    """(template, restaurant code or None, file name) in load order."""
    plan: list[tuple[str, str | None, str]] = [(t, None, f"{t}.csv") for t in REFERENCE_ORDER]
    codes = sorted({name.rsplit("_", 1)[1].split(".")[0] for name in net.files if name.startswith("sales_")})
    for code in codes:
        for t in FACT_ORDER:
            name = next((n for n in net.files if n.startswith(f"{t}_{code}.")), None)
            if name:  # not every restaurant has transfers
                plan.append((t, code, name))
    return plan
