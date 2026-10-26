"""Norms used until the network sets its own (answers to Q4, Q6; Q7 pending — docs/open-questions.md)."""

from decimal import Decimal

FOOD_COST_TARGET_PCT = Decimal(30)

# Allowed loss above recipes, % of usage, by product category. Овощи 3, мясо 2, напитки 1 — set by the
# customer; the rest are industry values. A category not listed uses the default.
LOSS_DEFAULT_PCT = Decimal(2)
LOSS_BY_CATEGORY_PCT = {
    "Овощи": Decimal(3),
    "Зелень": Decimal(3),
    "Мясо и птица": Decimal(2),
    "Рыба": Decimal(2),
    "Сыры": Decimal("1.5"),
    "Молочные": Decimal("1.5"),
    "Бакалея": Decimal(1),
    "Напитки": Decimal(1),
}

# Standard write-off reasons until the network sends its own list (Q7).
#   loss      — money lost (spoilage, kitchen mistakes, breakage)
#   planned   — planned use, not a loss (staff meals, tastings, compliments)
#   shortage  — written off to close a stock-count shortage: a signal for M4, not a real reason
WRITE_OFF_REASONS = [
    (
        "spoilage",
        "Порча, истек срок",
        "loss",
        ["порча", "истек срок", "просрочка", "испорчено", "срок годности"],
    ),
    ("kitchen", "Брак при приготовлении", "loss", ["брак", "брак кухни", "пересол", "пригорело"]),
    ("breakage", "Бой, разлив", "loss", ["бой", "разлив", "разбито", "пролито"]),
    ("staff_meal", "Питание персонала", "planned", ["питание персонала", "персонал", "стафф", "staff"]),
    ("tasting", "Проработка, дегустация", "planned", ["проработка", "дегустация", "тестовое блюдо"]),
    ("compliment", "Комплимент гостю", "planned", ["комплимент", "угощение", "представительские"]),
    ("shortage", "Недостача по инвентаризации", "shortage", ["недостача", "инвентаризация", "пересорт"]),
    ("other", "Прочее", "loss", []),
]
