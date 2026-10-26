"""Reading real-looking exports and validating them, without a database."""

import io
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import xlsxwriter

from app.core.errors import InvalidError
from app.imports.reader import read_table
from app.imports.templates import TEMPLATES
from app.imports.validate import Lookups, Ref, parse_date, parse_decimal, unit_of, validate

TODAY = date(2026, 10, 23)
MOZZ = Ref(uuid4(), "Сыр Моцарелла", "kg")
CREAM = Ref(uuid4(), "Сливки 33%", "l")
EGG = Ref(uuid4(), "Яйцо", "pcs")
MARG = Ref(uuid4(), "Маргарита")
SUP = Ref(uuid4(), "Сырный дом")


def lookups() -> Lookups:
    return Lookups(
        products={"P1": MOZZ, "P2": CREAM, "P3": EGG},
        product_names={r.name.lower(): r for r in (MOZZ, CREAM, EGG)},
        menu_items={"M1": MARG},
        menu_item_names={"маргарита": MARG},
        suppliers={"S1": SUP},
        supplier_names={"сырный дом": SUP},
    )


def run(template: str, text: str, filename: str = "f.csv", encoding: str = "utf-8"):  # type: ignore[no-untyped-def]
    t = TEMPLATES[template]
    return validate(t, read_table(text.encode(encoding), filename, t), lookups(), today=TODAY)


def test_values() -> None:
    assert parse_decimal("1 234,50") == Decimal("1234.50")
    assert parse_decimal("1.234.567,8") == Decimal("1234567.8")
    assert parse_decimal("580 ₽") == Decimal(580)
    assert (
        parse_date("01.10.2026")
        == parse_date("2026-10-01")
        == parse_date("2026-10-01 00:00:00")
        == date(2026, 10, 1)
    )
    assert unit_of("Кг.") == ("kg", Decimal(1))
    assert unit_of("гр") == ("kg", Decimal("0.001"))
    assert unit_of("упак") is None
    with pytest.raises(ValueError):
        parse_decimal("десять")


def test_semicolon_cp1251_with_synonyms_and_name_lookup() -> None:
    text = "Дата;Блюдо;Кол-во;Сумма\n01.10.2026;Маргарита;3;1 740,50\n02.10.2026;маргарита;2;1160\n"
    r = run("sales", text, encoding="cp1251")
    assert not r.errors
    assert [x["qty"] for x in r.records] == [Decimal(3), Decimal(2)]
    assert r.records[0]["revenue"] == Decimal("1740.50") and r.records[0]["menu_item_id"] == MARG.id
    assert (r.period_from, r.period_to) == (date(2026, 10, 1), date(2026, 10, 2))


def test_pretty_xlsx_with_title_and_totals_keeps_file_row_numbers() -> None:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf)
    ws = wb.add_worksheet()
    rows: list[list[object]] = [
        ["Отчет по продажам блюд за октябрь"],
        [],
        ["Дата", "Код блюда", "Количество", "Выручка"],
        ["01.10.2026", "M1", 3, 1740.5],
        ["01.10.2026", "M9", 1, 580],
        ["Итого", "", 4, 2320.5],
    ]
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            ws.write(i, j, v)
    wb.close()
    t = TEMPLATES["sales"]
    table = read_table(buf.getvalue(), "sales.xlsx", t)
    assert table.header_row == 3 and table.skipped_totals == 1
    r = validate(t, table, lookups(), today=TODAY)
    assert len(r.records) == 1
    # An unknown dish is not an error but a name to match once.
    assert r.errors == []
    assert [(u.kind, u.code, u.rows) for u in r.unmatched] == [("menu_item", "M9", [5])]
    assert any("итогов" in w.message for w in r.warnings)


def test_missing_required_columns_is_a_file_level_error() -> None:
    with pytest.raises(InvalidError, match="Количество"):
        run("sales", "Дата;Блюдо;Выручка\n01.10.2026;Маргарита;100\n")


def test_units_are_converted_to_base_and_unknown_or_incompatible_units_are_errors() -> None:
    text = (
        "Дата;Код товара;Количество;Ед. изм.;Сумма\n"
        "01.10.2026;P1;500;г;250\n"
        "01.10.2026;P1;2;упак;900\n"
        "01.10.2026;P1;3;шт;900\n"
        "01.10.2026;P3;30;шт;300\n"
    )
    r = run("receipts", text)
    assert [x["qty"] for x in r.records] == [Decimal("0.500"), Decimal(30)]
    assert [(e.row, e.column) for e in r.errors] == [(3, "Ед. изм."), (4, "Ед. изм.")]
    assert "неизвестная единица «упак» у товара «Сыр Моцарелла»" in r.errors[0].message
    assert "нужен коэффициент" in r.errors[1].message


def test_amount_check_is_a_warning_and_bad_values_are_errors() -> None:
    text = (
        "Дата;Поставщик;Товар;Количество;Цена;Сумма\n"
        "01.10.2026;Сырный дом;Сыр Моцарелла;10;600;6000\n"
        "02.10.2026;Сырный дом;Сыр Моцарелла;10;600;6500\n"
        "03.10.2026;Сырный дом;Сыр Моцарелла;десять;600;6000\n"
        "30.10.2026;Сырный дом;Сыр Моцарелла;1;600;600\n"
        "04.10.2026;Молочный двор;Сыр Моцарелла;1;600;600\n"
    )
    r = run("receipts", text)
    assert len(r.records) == 2 and r.records[0]["supplier_id"] == SUP.id
    assert [w.row for w in r.warnings] == [3]
    assert [(e.row, e.column) for e in r.errors] == [(4, "Количество"), (5, "Дата")]
    assert [(u.kind, u.name, u.rows) for u in r.unmatched] == [("supplier", "Молочный двор", [6])]
    assert "в будущем" in r.errors[1].message


def test_inventory_and_write_offs() -> None:
    inv = run(
        "inventory_counts", "Дата;Код товара;Учетный остаток;Фактический остаток\n01.10.2026;P1;45,5;43\n"
    )
    assert inv.records == [
        {
            "day": date(2026, 10, 1),
            "product_id": MOZZ.id,
            "book_qty": Decimal("45.5"),
            "actual_qty": Decimal(43),
        }
    ]
    wo = run("write_offs", "Дата;Товар;Количество;Ед. изм.;Причина\n01.10.2026;Сливки 33%;250;мл;Порча\n")
    assert wo.records[0]["qty"] == Decimal("0.250") and wo.records[0]["reason"] == "Порча"


def test_reference_templates() -> None:
    p = run("products", "Код;Наименование;Базовая ед.\nP9;Мука;кг\nP10;Соль;г\n")
    assert p.records[0]["base_unit"] == "kg"
    # Names match after normalisation: case, «ё», punctuation and spaces do not matter.
    sales = run("sales", "Дата;Блюдо;Кол-во;Сумма\n01.10.2026;  МАРГАРИТА. ;1;580\n")
    assert sales.records[0]["menu_item_id"] == MARG.id
    assert p.errors[0].row == 3 and "кг, л или шт" in p.errors[0].message
    s = run("suppliers", "Код;Название;ИНН\nS2;Мясной ряд;77071234\n")
    assert s.errors[0].column == "ИНН"
    rec = run("recipes", "Код блюда;Код товара;Брутто;Ед. изм.;Действует с\nM1;P1;120;г;01.08.2026\n")
    assert rec.records[0]["gross_qty"] == Decimal("0.120")


def test_period_includes_rows_waiting_for_a_name_match() -> None:
    r = run(
        "write_offs",
        "Дата;Товар;Количество\n01.10.2026;Моцарелла фиор ди латте;1\n05.10.2026;Сыр Моцарелла;2\n",
    )
    assert len(r.records) == 1 and r.unmatched[0].rows == [2]
    assert (r.period_from, r.period_to) == (date(2026, 10, 1), date(2026, 10, 5))


def test_semi_finished_products_and_their_recipes() -> None:
    p = run(
        "products",
        "Код;Наименование;Базовая ед.;Тип\nP20;Соус томатный;кг;п/ф\nP21;Мука;кг;товар\nP22;Соль;кг;смесь\n",
    )
    assert [r["is_semi"] for r in p.records] == [True, False]
    assert p.errors[0].column == "Тип"
    lk = lookups()
    sauce = Ref(uuid4(), "Соус томатный", "kg", is_semi=True)
    lk.products["P20"] = sauce
    t = TEMPLATES["recipes"]
    text = (
        "Код блюда;Код товара;Брутто;Ед. изм.;Действует с\n"
        "P20;P1;1250;г;01.08.2026\n"
        "M1;P20;80;г;01.08.2026\n"
        "P1;P2;1;л;01.08.2026\n"
    )
    r = validate(t, read_table(text.encode(), "r.csv", t), lk, today=TODAY)
    assert r.records[0]["semi_product_id"] == sauce.id and r.records[0]["menu_item_id"] is None
    assert r.records[1]["menu_item_id"] == MARG.id and r.records[1]["product_id"] == sauce.id
    assert [(e.row, e.column) for e in r.errors] == [(4, "Код блюда")]
    assert "не полуфабрикат" in r.errors[0].message


def test_transfers_keep_outgoing_and_skip_incoming() -> None:
    a1, a2 = uuid4(), uuid4()
    lk = lookups()
    lk.resolve_restaurant = {"R01": a1, "Ресторан на Арбате": a2}.get
    lk.own_restaurant_id = a1
    t = TEMPLATES["transfers"]
    text = (
        "Дата;Откуда;Куда;Код товара;Количество\n"
        "01.10.2026;R01;Ресторан на Арбате;P1;2\n"
        "02.10.2026;Ресторан на Арбате;R01;P1;1\n"
        "03.10.2026;R01;R01;P1;1\n"
        "04.10.2026;R01;Ресторан где-то;P1;1\n"
    )
    r = validate(t, read_table(text.encode(), "t.csv", t), lk, today=TODAY)
    assert r.records == [
        {"day": date(2026, 10, 1), "to_restaurant_id": a2, "product_id": MOZZ.id, "qty": Decimal(2)}
    ]
    assert r.skipped == 1 and any("отправителя" in w.message for w in r.warnings)
    assert [(e.row, e.column) for e in r.errors] == [(4, "Куда"), (5, "Куда")]
