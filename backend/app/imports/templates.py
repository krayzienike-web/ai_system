"""Canonical import templates (docs/04-data-import.md). Real exports are mapped onto them by column synonyms;
saved source profiles come next (docs/09-data-requirements.md, «Адаптивный импорт»)."""

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    TEXT = "text"
    DECIMAL = "decimal"
    INT = "int"
    DATE = "date"


class Scope(StrEnum):
    NETWORK = "network"  # reference data of the whole network: HQ only
    RESTAURANT = "restaurant"  # facts of one restaurant


@dataclass(frozen=True)
class Column:
    name: str
    title: str  # how the user sees it in the template and in error messages
    kind: Kind = Kind.TEXT
    required: bool = False
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    scope: Scope
    columns: tuple[Column, ...]
    # Groups where at least one column must be present (a product by code or by name).
    one_of: tuple[tuple[str, ...], ...] = ()

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)


def _c(name: str, title: str, kind: Kind = Kind.TEXT, required: bool = False, *synonyms: str) -> Column:
    return Column(name, title, kind, required, (title.lower(), *synonyms))


PRODUCT = (
    _c("product_code", "Код товара", Kind.TEXT, False, "артикул", "код номенклатуры", "код продукта"),
    _c(
        "product_name",
        "Товар",
        Kind.TEXT,
        False,
        "номенклатура",
        "наименование товара",
        "продукт",
        "ингредиент",
    ),
)
UNIT = _c("unit", "Ед. изм.", Kind.TEXT, False, "ед.", "ед", "единица", "единица измерения", "ед изм")
DAY = _c("day", "Дата", Kind.DATE, True, "дата документа", "день", "учетный день", "date")

TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        Template(
            "restaurants",
            "Рестораны",
            Scope.NETWORK,
            (
                _c("code", "Код", Kind.TEXT, True, "код ресторана", "код точки"),
                _c("name", "Название", Kind.TEXT, True, "ресторан", "наименование", "точка"),
                _c("city", "Город"),
            ),
        ),
        Template(
            "products",
            "Номенклатура",
            Scope.NETWORK,
            (
                _c("code", "Код", Kind.TEXT, True, "код товара", "артикул"),
                _c("name", "Наименование", Kind.TEXT, True, "товар", "номенклатура", "название"),
                _c("category", "Категория", Kind.TEXT, False, "группа"),
                _c("unit", "Базовая ед.", Kind.TEXT, True, "ед. изм.", "ед.", "единица измерения", "ед изм"),
                _c("shelf_life_days", "Срок годности, дней", Kind.INT, False, "срок годности"),
            ),
        ),
        Template(
            "suppliers",
            "Поставщики",
            Scope.NETWORK,
            (
                _c("code", "Код", Kind.TEXT, True, "код поставщика"),
                _c("name", "Название", Kind.TEXT, True, "поставщик", "контрагент", "наименование"),
                _c("inn", "ИНН"),
            ),
        ),
        Template(
            "menu_items",
            "Блюда",
            Scope.NETWORK,
            (
                _c("code", "Код", Kind.TEXT, True, "код блюда"),
                _c("name", "Блюдо", Kind.TEXT, True, "наименование", "название"),
                _c("category", "Категория", Kind.TEXT, False, "группа", "раздел меню"),
                _c("price", "Цена", Kind.DECIMAL, False, "цена продажи"),
            ),
        ),
        Template(
            "recipes",
            "Технологические карты (ТТК)",
            Scope.NETWORK,
            (
                _c("menu_item_code", "Код блюда", Kind.TEXT, True, "блюдо код"),
                *PRODUCT,
                _c(
                    "gross_qty",
                    "Брутто",
                    Kind.DECIMAL,
                    True,
                    "кол-во брутто",
                    "количество брутто",
                    "вес брутто",
                ),
                UNIT,
                _c("valid_from", "Действует с", Kind.DATE, True, "дата начала", "с даты"),
            ),
            one_of=(("product_code", "product_name"),),
        ),
        Template(
            "sales",
            "Продажи",
            Scope.RESTAURANT,
            (
                DAY,
                _c("menu_item_code", "Код блюда", Kind.TEXT, False, "код"),
                _c("menu_item_name", "Блюдо", Kind.TEXT, False, "наименование блюда", "наименование"),
                _c("qty", "Количество", Kind.DECIMAL, True, "кол-во", "кол-во блюд", "количество блюд"),
                _c("revenue", "Выручка", Kind.DECIMAL, True, "сумма", "сумма со скидкой", "выручка, ₽"),
                _c("discount", "Скидка", Kind.DECIMAL, False, "сумма скидки"),
            ),
            one_of=(("menu_item_code", "menu_item_name"),),
        ),
        Template(
            "receipts",
            "Приходы (накладные)",
            Scope.RESTAURANT,
            (
                DAY,
                _c(
                    "doc_no",
                    "№ накладной",
                    Kind.TEXT,
                    False,
                    "номер накладной",
                    "номер документа",
                    "документ",
                ),
                _c("supplier_code", "Код поставщика"),
                _c("supplier_name", "Поставщик", Kind.TEXT, False, "контрагент"),
                *PRODUCT,
                _c("qty", "Количество", Kind.DECIMAL, True, "кол-во"),
                UNIT,
                _c("price", "Цена", Kind.DECIMAL, False, "цена за ед."),
                _c("amount", "Сумма", Kind.DECIMAL, True, "сумма с ндс", "сумма, ₽"),
                _c("vat", "НДС", Kind.DECIMAL, False, "сумма ндс"),
            ),
            one_of=(("product_code", "product_name"),),
        ),
        Template(
            "write_offs",
            "Списания",
            Scope.RESTAURANT,
            (
                DAY,
                *PRODUCT,
                _c("qty", "Количество", Kind.DECIMAL, True, "кол-во"),
                UNIT,
                _c("reason", "Причина", Kind.TEXT, False, "статья списания", "основание"),
            ),
            one_of=(("product_code", "product_name"),),
        ),
        Template(
            "inventory_counts",
            "Инвентаризации",
            Scope.RESTAURANT,
            (
                DAY,
                *PRODUCT,
                _c(
                    "book_qty",
                    "Учетный остаток",
                    Kind.DECIMAL,
                    False,
                    "остаток по учету",
                    "учетное количество",
                ),
                _c("actual_qty", "Фактический остаток", Kind.DECIMAL, True, "факт", "фактическое количество"),
                UNIT,
            ),
            one_of=(("product_code", "product_name"),),
        ),
    )
}
