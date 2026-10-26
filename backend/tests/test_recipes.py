from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.catalog.recipes import Line, RecipeCycleError, explode, find_cycle, lines_on

PIZZA, SAUCE, BASE, TOMATO, OIL, CHEESE, GARLIC = (uuid4() for _ in range(7))
D = Decimal
V1, V2 = date(2026, 1, 1), date(2026, 8, 1)

LINES = [
    Line(PIZZA, CHEESE, D("0.14"), V1),
    Line(PIZZA, SAUCE, D("0.08"), V1),
    # 1 kg of sauce: 1.25 kg tomatoes, 0.2 kg of garlic base
    Line(SAUCE, TOMATO, D("1.25"), V1),
    Line(SAUCE, BASE, D("0.2"), V1),
    # 1 kg of garlic base: 0.5 kg garlic, 0.6 l oil
    Line(BASE, GARLIC, D("0.5"), V1),
    Line(BASE, OIL, D("0.6"), V1),
    # From August the pizza takes more cheese.
    Line(PIZZA, CHEESE, D("0.16"), V2),
    Line(PIZZA, SAUCE, D("0.08"), V2),
]


def test_version_valid_on_a_day() -> None:
    july = lines_on(LINES, date(2026, 7, 31))
    august = lines_on(LINES, date(2026, 8, 1))
    assert {x.gross_qty for x in july[PIZZA] if x.product_id == CHEESE} == {D("0.14")}
    assert {x.gross_qty for x in august[PIZZA] if x.product_id == CHEESE} == {D("0.16")}
    assert lines_on(LINES, date(2025, 12, 31)) == {}


def test_nested_semi_finished_products_expand_to_raw_exactly() -> None:
    raw = explode(PIZZA, D(10), lines_on(LINES, date(2026, 7, 1)))
    assert raw == {
        CHEESE: D("1.40"),
        TOMATO: D("1.0000"),  # 10 × 0.08 × 1.25
        GARLIC: D("0.08000"),  # 10 × 0.08 × 0.2 × 0.5
        OIL: D("0.09600"),
    }


def test_semi_finished_product_can_be_expanded_on_its_own() -> None:
    assert explode(SAUCE, D(2), lines_on(LINES, V1)) == {TOMATO: D("2.50"), GARLIC: D("0.20"), OIL: D("0.24")}


def test_cycles_are_found_and_refused() -> None:
    assert find_cycle(lines_on(LINES, V1)) is None
    looped = [*LINES, Line(BASE, SAUCE, D("0.1"), V1)]  # garlic base now contains sauce
    recipes = lines_on(looped, V1)
    cycle = find_cycle(recipes)
    assert cycle is not None and cycle[0] == cycle[-1] and set(cycle) == {SAUCE, BASE}
    with pytest.raises(RecipeCycleError):
        explode(PIZZA, D(1), recipes)
