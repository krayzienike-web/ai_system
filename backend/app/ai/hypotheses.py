"""«Почему так» и «что делать» по находке (ADR 0008, stage 5.5).

The code found the deviation and gathered what changed around it (`finding_context`); the assistant proposes
up to three likely causes from a fixed list — so a proposal can be compared with the planted cause of the demo
network (the eval) — how to check each on the spot, and steps that respect the network's rules. A director
gets them for their own findings, the HQ for any.
"""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai import finding_context
from app.ai.gateway import Gateway
from app.ai.suggestions import Proposal, ask, propose
from app.insights.models import Finding
from app.tenancy.context import AccessContext, user_session

# The causes a proposal names, by code (the eval compares codes, the screen shows the words).
CAUSES: dict[str, str] = {
    "portioning": "Порции больше техкарты (перекладывают на кухне)",
    "yield": "Выход при разделке или обработке ниже нормы",
    "recipe_error": "Техкарта устарела или с ошибкой",
    "theft": "Хищение или неучтенный расход",
    "expensive_supplier": "Закупка у дорогого поставщика, срочные заказы",
    "supplier_overprice": "Поставщик продает дороже, чем другим или чем договорились",
    "market_price": "Цена выросла у поставщика или на рынке",
    "menu_price_lag": "Цена в меню не успела за себестоимостью",
    "overordering": "Заказ больше, чем успевают продать до срока годности",
    "weekday_demand": "Заказ не учитывает спрос по дням недели",
    "write_offs_before_count": "Списания подгоняют под инвентаризацию",
    "mis_sort": "Пересорт при инвентаризации",
    "paper_count": "Инвентаризация «на бумаге», без пересчета",
    "count_skipped": "Инвентаризацию пропустили",
    "short_delivery": "Поставка меньше нужного",
    "export_gap": "Данные выгружены не полностью",
    "missing_recipe": "Блюдо продается без техкарты",
    "storage": "Нарушены условия хранения",
    "one_off": "Разовое событие: банкет, праздник, ремонт",
}
Cause = Literal[
    "portioning",
    "yield",
    "recipe_error",
    "theft",
    "expensive_supplier",
    "supplier_overprice",
    "market_price",
    "menu_price_lag",
    "overordering",
    "weekday_demand",
    "write_offs_before_count",
    "mis_sort",
    "paper_count",
    "count_skipped",
    "short_delivery",
    "export_gap",
    "missing_recipe",
    "storage",
    "one_off",
]


class Hypothesis(BaseModel):
    cause: Cause
    likelihood: Literal["высокая", "средняя", "низкая"]
    why: str = Field(description="Почему эта причина вероятна — по фактам")
    check: str = Field(description="Как проверить на месте, за один день")


class Hypotheses(BaseModel):
    hypotheses: list[Hypothesis] = Field(description="От самой вероятной, не больше трех")
    steps: list[str] = Field(description="Что сделать, с учетом правил сети")
    rules_note: str | None = Field(description="Как правила сети меняют шаги, если меняют")


def _at_most_three(h: Hypotheses) -> list[str]:
    problems = []
    if not 1 <= len(h.hypotheses) <= 3:
        problems.append(f"гипотез должно быть от 1 до 3, а не {len(h.hypotheses)}")
    if len({x.cause for x in h.hypotheses}) != len(h.hypotheses):
        problems.append("причины повторяются")
    return problems


BASIS_WORDS = {
    "suppliers_by_month": "поставщики и цены по месяцам",
    "write_off_reasons": "причины списаний",
    "inventory_count_days": "даты инвентаризаций",
    "data_problems": "проблемы с данными ресторана",
    "checks_of_similar_findings": "итоги похожих проверок в сети",
}


def basis_words(basis: dict[str, Any]) -> list[str]:
    """What the hypotheses rest on, in words: only the facts there were (empty ones are dropped when the
    context is built; code review 02.11.2026, front p. 6)."""
    out = [words for key, words in BASIS_WORDS.items() if basis.get(key)]
    rules = basis.get("network_rules") or []
    if rules:
        out.append("правила сети: " + "; ".join(rules))
    return out or ["данные находки"]


def _facts(ctx: AccessContext, finding_id: UUID, today: date) -> tuple[dict[str, Any], UUID | None]:
    with user_session(ctx) as session:
        basis = finding_context.build(session, ctx, finding_id, today)  # not visible → NotFoundError
        row = session.get(Finding, finding_id)
        restaurant_id = row.restaurant_id if row else None
    basis["causes_to_choose_from"] = CAUSES
    return basis, restaurant_id


def ask_for_finding(gateway: Gateway, ctx: AccessContext, finding_id: UUID, today: date) -> Hypotheses:
    """The hypotheses without keeping them: the eval measures, it does not replace what people see (code
    review 02.11.2026, p. 14)."""
    basis, _ = _facts(ctx, finding_id, today)
    result, _ = ask(
        gateway,
        ctx,
        task="explain",
        prompt_name="hypotheses",
        basis=basis,
        answer=Hypotheses,
        check=_at_most_three,
    )
    return result


def propose_for_finding(gateway: Gateway, ctx: AccessContext, finding_id: UUID, today: date) -> Proposal:
    basis, restaurant_id = _facts(ctx, finding_id, today)
    return propose(
        gateway,
        ctx,
        kind="hypotheses",
        task="explain",
        prompt_name="hypotheses",
        basis=basis,
        answer=Hypotheses,
        subject_id=finding_id,
        restaurant_id=restaurant_id,
        check=_at_most_three,
    )
