"""Recipes (ТТК) with semi-finished products: the version valid on a day, the breakdown of a dish into
raw products, and the cycle check. Pure functions: analytics (theoretical usage, M1/M2) builds on them.

A semi-finished product (соус, тесто) is a product with its own recipe per 1 base unit (1 kg, 1 l, 1 pc).
Dishes and other semi-finished products use it like any product; nesting may go to any depth (open
question Q1: assumed). Domain invariant 3: semi-finished products are expanded recursively, cycles refused.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

MAX_DEPTH = 20  # far beyond any real kitchen; a deeper chain means bad data


@dataclass(frozen=True)
class Line:
    parent_id: UUID  # a menu item or a semi-finished product
    product_id: UUID
    gross_qty: Decimal  # per portion of a dish, or per 1 base unit of a semi-finished product
    valid_from: date


def lines_on(lines: list[Line], day: date) -> dict[UUID, list[Line]]:
    """For every parent, the lines of its recipe version valid on `day` (the latest valid_from ≤ day)."""
    by_version: dict[UUID, dict[date, list[Line]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        if line.valid_from <= day:
            by_version[line.parent_id][line.valid_from].append(line)
    return {parent: versions[max(versions)] for parent, versions in by_version.items()}


class RecipeCycleError(ValueError):
    def __init__(self, path: list[UUID]) -> None:
        super().__init__("recipe cycle")
        self.path = path


def find_cycle(recipes: dict[UUID, list[Line]]) -> list[UUID] | None:
    """A chain of semi-finished products that leads back to itself, or None."""
    state: dict[UUID, int] = {}  # 1: on the current path, 2: done

    def visit(node: UUID, path: list[UUID]) -> list[UUID] | None:
        state[node] = 1
        for line in recipes.get(node, []):
            child = line.product_id
            if state.get(child) == 1:
                return [*path, node, child][[*path, node, child].index(child) :]
            if child in recipes and state.get(child) is None:
                found = visit(child, [*path, node])
                if found:
                    return found
        state[node] = 2
        return None

    for parent in recipes:
        if state.get(parent) is None:
            cycle = visit(parent, [])
            if cycle:
                return cycle
    return None


def explode(parent_id: UUID, qty: Decimal, recipes: dict[UUID, list[Line]]) -> dict[UUID, Decimal]:
    """Raw products needed for `qty` of a dish (portions) or of a semi-finished product (base units).

    A product without a recipe is raw. Quantities are kept exact (Decimal) — no rounding until reporting.
    """
    out: dict[UUID, Decimal] = defaultdict(Decimal)

    def walk(node: UUID, amount: Decimal, path: tuple[UUID, ...]) -> None:
        if len(path) > MAX_DEPTH:
            raise RecipeCycleError(list(path))
        for line in recipes.get(node, []):
            need = amount * line.gross_qty
            if line.product_id in recipes:
                if line.product_id in path:
                    raise RecipeCycleError([*path, line.product_id])
                walk(line.product_id, need, (*path, line.product_id))
            else:
                out[line.product_id] += need

    walk(parent_id, qty, (parent_id,))
    return dict(out)
