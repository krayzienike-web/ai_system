"""An agent's note in words by rules (ADR 0010): the title, the text and the list. Every number comes from the
facts as it is; the model, when it is on, rewrites only the text (`ai/agent_writer.py`) and the list stays."""

from datetime import date
from decimal import Decimal
from typing import Any

from app.agents.models import Agent
from app.analytics.drafts import dmy, rub
from app.imports.templates import TEMPLATES

UNITS = {"kg": "кг", "l": "л", "pcs": "шт"}


def _d(iso: str) -> str:
    return dmy(date.fromisoformat(iso))


def _days(n: int) -> str:
    if n == 0:
        return "сегодня"
    if n == 1:
        return "завтра"
    word = (
        "день"
        if n % 10 == 1 and n % 100 != 11
        else "дня"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
        else "дней"
    )
    return f"через {n} {word}"


def _positions(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} позиция"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} позиции"
    return f"{n} позиций"


def _steps(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} шаг"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} шага"
    return f"{n} шагов"


def _product_line(p: dict[str, Any], last: str) -> str:
    name = p["name"]
    if p["reason"] == "finding":
        return f"{name} — по нему открыта находка «{p['finding']}»"
    if p["reason"] == "shortage":
        return f"{name} — на пересчете {_d(last)} не хватило на {rub(Decimal(p['diff_rub']))}"
    return f"{name} — дорогой остаток: {rub(Decimal(p['stock_rub']))} на {_d(last)}"


def inventory(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    items = [_product_line(p, f["last_count"]) for p in f["products"]]
    title = f"Инвентаризация {_d(f['count_on'])}: что пересчитать внимательно"
    text = (
        f"Пересчет {_days(f['days_left'])}, {_d(f['count_on'])}. По прошлому пересчету {_d(f['last_count'])} "
        f"и открытым находкам в списке {_positions(len(items))}: их стоит пересчитать первыми и дважды."
    )
    return title, text, items


def task_due(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    left = f["steps_left"]
    title = f"Срок задачи {_days(f['days_left'])}: {f['task']}"
    if f["steps_total"]:
        rest = f"осталось {_steps(len(left))} из {f['steps_total']}" if left else "все шаги отмечены"
        text = f"Задача «{f['task']}» — срок {_d(f['due_on'])}, {rest}."
    else:
        text = (
            f"Задача «{f['task']}» — срок {_d(f['due_on'])}. Отметьте ее выполненной и напишите, что сделано."
        )
    if f["status"] == "assigned":
        text += " Задача еще не начата."
    return title, text, left


def task_stuck(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    title = "Задача просрочена и не начата"  # the card names the restaurant
    text = (
        f"«{f['task']}» — срок был {_d(f['due_on'])}, просрочена на {f['days_late']} дн., "
        "к ней еще не приступили. "
        f"Можно перенести срок на {_d(f['move_to'])} или обсудить задачу с директором."
    )
    return title, text, []


def _missing_line(m: dict[str, Any]) -> str:
    title = TEMPLATES[m["template"]].title
    if m["status"] == "missing":
        return f"{title} — ни одной выгрузки"
    return f"{title} — последние данные за {_d(m['last_date'])}"


def data_check(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    items = [_missing_line(m) for m in f["missing"]]
    title = "Не хватает данных: загрузите до пересчета находок"
    text = (
        "Утренняя проверка: за последнюю неделю пришли не все выгрузки. Пока их нет, находки считаются "
        "по неполным данным. Загрузите их на экране «Данные»."
    )
    return title, text, items


RULES = {
    Agent.INVENTORY_PREP: inventory,
    Agent.TASK_DUE: task_due,
    Agent.TASK_STUCK: task_stuck,
    Agent.DATA_CHECK: data_check,
}


def by_rules(agent: str, facts: dict[str, Any]) -> tuple[str, str, list[str]]:
    return RULES[Agent(agent)](facts)
