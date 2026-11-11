"""Which header a column takes when a file has two for it (Q36, answered 11.11.2026)."""

import pytest

from app.imports.reader import map_header
from app.imports.templates import TEMPLATES

SALES = TEMPLATES["sales"]


@pytest.mark.parametrize(
    "header",
    [
        ["Дата", "Блюдо", "Количество", "Сумма", "Сумма со скидкой"],
        ["Дата", "Блюдо", "Количество", "Сумма со скидкой", "Сумма"],
    ],
)
def test_the_revenue_is_the_amount_after_the_discount_whatever_the_order(header: list[str]) -> None:
    """TC-IMP-38: «Сумма со скидкой» is the revenue, even with «Сумма» to its left; «Сумма» is not used."""
    found, unmapped = map_header(header, SALES)
    assert header[found["revenue"]] == "Сумма со скидкой"
    assert unmapped == ["Сумма"]


def test_a_single_amount_is_still_the_revenue() -> None:
    found, unmapped = map_header(["Дата", "Блюдо", "Кол-во", "Сумма"], SALES)
    assert found["revenue"] == 3 and unmapped == []


def test_the_template_word_beats_a_profile_alias_and_the_alias_fills_a_gap() -> None:
    """A profile's header ranks after every synonym: it fills a column the file has no synonym for."""
    found, unmapped = map_header(["Дата", "Блюдо", "Кол-во", "Итого", "Выручка"], SALES, {"итого": "revenue"})
    assert found["revenue"] == 4 and unmapped == ["Итого"]
    found, _ = map_header(["Дата", "Блюдо", "Кол-во", "Итого"], SALES, {"итого": "revenue"})
    assert found["revenue"] == 3
