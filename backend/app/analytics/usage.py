"""Theoretical usage: what the recipes say should have been used for what was sold (docs/02, M1)."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.analytics.facts import Facts
from app.catalog.recipes import explode, lines_on


class Usage:
    """Raw products per restaurant and day, from sales × the recipe version valid on the day of sale.

    A recipe epoch starts on every date some recipe changes; within an epoch every dish breaks down the same
    way, so each (dish, epoch) is exploded once. Dishes without a recipe add nothing (M7 reports them).
    """

    def __init__(self, facts: Facts) -> None:
        epochs = sorted({line.valid_from for line in facts.recipe_lines})
        recipes_at = {e: lines_on(facts.recipe_lines, e) for e in epochs}
        cache: dict[tuple[UUID, date], dict[UUID, Decimal]] = {}

        def per_portion(item: UUID, day: date) -> dict[UUID, Decimal]:
            valid = [e for e in epochs if e <= day]
            if not valid:
                return {}
            key = (item, valid[-1])
            if key not in cache:
                cache[key] = explode(item, Decimal(1), recipes_at[valid[-1]])
            return cache[key]

        self.by_day: dict[tuple[UUID, UUID], dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        self.without_recipe: dict[UUID, Decimal] = defaultdict(Decimal)  # menu item -> portions sold
        for s in facts.sales:
            need = per_portion(s.menu_item, s.day)
            if not need:
                self.without_recipe[s.menu_item] += s.qty
            for product, qty in need.items():
                self.by_day[(s.restaurant, product)][s.day] += qty * s.qty

    def total(self, restaurant: UUID, product: UUID, start: date, end: date) -> Decimal:
        """Usage over start..end inclusive."""
        days = self.by_day.get((restaurant, product), {})
        return sum((q for d, q in days.items() if start <= d <= end), Decimal(0))
