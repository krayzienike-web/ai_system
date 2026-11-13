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


def _count(n: int, words: tuple[str, str, str]) -> str:
    """«1 день», «3 дня», «5 дней»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {words[0]}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {words[1]}"
    return f"{n} {words[2]}"


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
        "Утренняя проверка: не все выгрузки свежие. Пока их нет, находки считаются "
        "по неполным данным. Загрузите их на экране «Данные»."
    )
    return title, text, items


def _u(f: dict[str, Any]) -> str:
    unit: str = f["unit"]
    return UNITS.get(unit, unit)


def plain(value: Decimal) -> str:
    """A quantity without trailing zeros and never in exponent form: 100, 2.5 (not «1E+2»)."""
    return format(value.normalize(), "f")


def num(value: str) -> str:
    """«2.5» → «2,5»: a quantity as people write it."""
    return value.replace(".", ",")


def _ddmm(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m")


def _agreed(f: dict[str, Any]) -> str:
    low, high = Decimal(f.get("reference_min") or f["reference"]), Decimal(f["reference"])
    return rub(high) if low == high else f"от {rub(low)} до {rub(high)}"


def _invoices(n: int) -> str:
    """«в 1 накладной», «в 3 накладных», «в 21 накладной» (test engineer after the stage 10 review)."""
    return _count(n, ("накладной", "накладных", "накладных"))


def supplier_claim(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    u, contract = _u(f), f["kind"] == "contract"
    lines = [
        f"№ {x['doc'] or 'без номера'} от {_d(x['day'])}, {x['restaurant']}: {num(x['qty'])} {u} по "
        f"{rub(Decimal(x['price']))} — {'переплата' if contract else 'разница'} {rub(Decimal(x['extra']))}"
        for x in f["invoices"]
    ]
    shown = len(f["invoices"])
    more = f" В списке — первые {shown} из {f['invoices_total']}." if f["invoices_total"] > shown else ""
    if contract:
        title = f"Претензия «{f['supplier']}»: {f['product'].lower()} дороже договора"
        text = (
            f"«{f['supplier']}», по договору поставки (п. ___) цена товара «{f['product']}» — "
            f"{_agreed(f)}/{u}. С {_d(f['since'])} по {_d(f['until'])} в "
            f"{_invoices(f['invoices_total'])} она выше, в среднем {rub(Decimal(f['price']))}/{u}. "
            f"Переплата — {rub(Decimal(f['extra']))}. Просим вернуть переплату или выставить "
            f"корректировочные счета-фактуры.{more}"
        )
    else:
        title = f"Запрос «{f['supplier']}»: рост цены на {f['product'].lower()}"
        text = (
            f"«{f['supplier']}», с {_d(f['since'])} цена товара «{f['product']}» выросла с "
            f"{rub(Decimal(f['reference']))} до {rub(Decimal(f['price']))}/{u} (+{num(f['growth_pct'])}%). "
            f"Просим обосновать повышение или вернуть прежнюю цену. По {_d(f['until'])} разница — "
            f"{rub(Decimal(f['extra']))} в {_invoices(f['invoices_total'])}.{more}"
        )
    return title, text, lines


def transfer(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    u, qty = _u(f), num(f["qty"])
    title = f"Перемещение: {f['product'].lower()} из «{f['from']}» в «{f['to']}»"
    runs_out = (
        f"по расчету закончится {_ddmm(f['zero_day'])}"
        if f["zero_day"] >= f["by"]
        else f"по расчету закончилась {_ddmm(f['zero_day'])}"
    )
    text = (
        f"В «{f['to']}» {f['product'].lower()} {runs_out}, поставка — {_ddmm(f['next_delivery'])}: до нее "
        f"нужно {qty} {u}. В «{f['from']}» по остаткам на {_ddmm(f['from_stock_day'])} — "
        f"{num(f['from_stock'])} {u} при закупке ≈ {num(f['from_daily'])} {u} в день: после передачи у них "
        f"останется запас больше чем на {_count(f['keep_days'], ('день', 'дня', 'дней'))}. "
        f"Передать {qty} {u} до {_ddmm(f['by'])}."
    )
    return title, text, []


def hq_agenda(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    items = [
        f"Находка: {x['title']} — {x['place']}, ≈ {rub(Decimal(x['effect']))} в месяц" for x in f["findings"]
    ]
    items += [f"Просрочена: {x['title']} — {x['place']}, на {x['days']} дн." for x in f["late"]]
    items += [f"Ждет запуска: {x}" for x in f["checks"]]
    title = f"Повестка планерки: неделя с {_ddmm(f['week'])}"
    text = (
        f"На этой неделе: самые дорогие открытые находки, просроченных задач — {f['late_total']}, "
        f"проверок ждут запуска — {f['checks_total']}, находок ждут решения — {f['awaiting']}."
    )
    return title, text, items


VERSIONS = {
    "supplier": (
        "сменился или добавился поставщик — вес или фасовка могли измениться",
        "взвесить ближайшую поставку при приемке и сверить с накладной",
    ),
    "no_write_offs": (
        "списаний нет совсем — порча и брак могли уходить без записи",
        "спросить, куда девают испорченное, и проверить журнал списаний",
    ),
    "moved_out": (
        "товар уходил перемещениями — проверить, что второй ресторан их принял",
        "сверить перемещения с приходом у получателя",
    ),
    "growing": (
        "перерасход растет от пересчета к пересчету — что-то изменилось",
        "выяснить, что поменялось: люди на заготовке, поставщик, меню",
    ),
    "portions": (
        "расход выше техкарт каждый раз — порции больше нормы или техкарта устарела",
        "взвесить 5 порций на раздаче и сверить с техкартой",
    ),
}


def _bought(p: dict[str, Any], u: str) -> str:
    if not p["bought"]:
        return "закупок не было"
    return "закуплено " + ", ".join(f"{num(q)} {u} у «{name}»" for name, q in p["bought"].items())


def shortage_story(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    u = _u(f)
    items = []
    for p in f["periods"]:
        line = (
            f"{_ddmm(p['from'])}–{_ddmm(p['to'])}: по пересчетам {num(p['actual'])} {u}, по техкартам "
            f"{num(p['theory'])} {u} (+{num(p['share'])}%), списано {num(p['written_off'])} {u}; "
            f"{_bought(p, u)}"
        )
        if p["moved_out"] != "0":
            line += f"; передано в другие рестораны {num(p['moved_out'])} {u}"
        if p["moved_in"] != "0":
            line += f"; получено {num(p['moved_in'])} {u}"
        items.append(line)
    causes = "; ".join(f"{i}) {VERSIONS[v][0]}" for i, v in enumerate(f["versions"], 1))
    checks = "; ".join(VERSIONS[v][1] for v in f["versions"])
    effect = f" ≈ {rub(Decimal(f['effect']))} в месяц" if f["effect"] else ""
    title = f"Недостача: {f['product'].lower()} в «{f['restaurant']}» — версии"
    text = (
        f"Перерасход{effect}, по сети обычно +{num(f['network_share'])}%. Возможные причины: {causes}. "
        f"Что проверить на месте: {checks}. Вывод — за аналитиком."
    )
    return title, text, items


def _kop(value: str) -> str:
    """«1.30» → «1,30 ₽», «1555.05» → «1 555,05 ₽»: a price, to the kopeck."""
    return f"{big(value)} ₽"


def big(value: str) -> str:
    """«19459.3» → «19 459,3»: thousands apart, as in the money."""
    whole, _, part = value.partition(".")
    sign = "-" if whole.startswith("-") else ""
    grouped = f"{int(whole.lstrip('-') or 0):,}".replace(",", " ")
    return sign + grouped + ("," + part if part else "")


BUYERS = (
    "ресторан нашей сети закупает",
    "ресторана нашей сети закупают",
    "ресторанов нашей сети закупают",
)


def supplier_deal(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    items = []
    for p in f["products"]:
        u = UNITS.get(p["unit"], p["unit"])
        items.append(
            f"{p['product']}: {big(p['qty_month'])} {u} в месяц, "
            f"{_count(p['restaurants'], ('ресторан платит', 'ресторана платят', 'ресторанов платят'))} "
            f"от {_kop(p['low'])} до {_kop(p['high'])}/{u}, медиана {_kop(p['median'])} — цена по "
            "медиане сэкономит ≈ "
            f"{rub(Decimal(p['saving_month']))} в месяц"
        )
    if f["products_total"] > len(f["products"]):
        items.append(f"Еще товаров с разной ценой: {f['products_total'] - len(f['products'])}")
    items.append(
        f"Для переговоров: единая цена по медиане — ≈ {rub(Decimal(f['saving_month']))} в месяц, каждый "
        f"процент скидки на весь объем — ≈ {rub(Decimal(f['one_pct_month']))} в месяц"
    )
    first = f["products"][0]
    u = UNITS.get(first["unit"], first["unit"])
    title = f"Переговоры с «{f['supplier']}»: единая цена для сети"
    text = (
        f"«{f['supplier']}», "
        f"{_count(f['restaurants'], BUYERS)} "
        "у вас в среднем на "
        f"{rub(Decimal(f['spend_month']))} в месяц. С {_d(f['since'])} по {_d(f['until'])} рестораны "
        f"платили за одни и те же товары разную цену: например, «{first['product']}» — от "
        f"{_kop(first['low'])} до {_kop(first['high'])}/{u}. Просим установить для всех "
        "ресторанов сети единую цену не выше "
        f"{_kop(first['median'])}/{u} и обсудить скидку за объем закупок по договору (п. ___)."
    )
    return title, text, items


def recipe_update(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    u = _u(f)
    items = []
    for d in f["dishes"]:
        kind = "полуфабрикат" if d["semi"] else "блюдо"
        line = f"{d['name']} ({kind}): {num(d['old'])} → {num(d['new'])} {u}"
        if d["cost"] is not None:
            line += f", себестоимость {'порции' if not d['semi'] else 'выхода'} +{_kop(d['cost'])}"
        items.append(line)
    if f.get("changed"):
        items.append(f"Уже изменены после этого периода, их не трогаем: {', '.join(f['changed'])}")
    period = f" ({_ddmm(f['since'])}–{_ddmm(f['until'])})" if f["since"] and f["until"] else ""
    title = f"Техкарта: новая норма «{f['product']}»"
    text = (
        f"Шеф-технологу: {f['restaurants_over']} из {f['restaurants']} ресторанов расходуют "
        f"«{f['product']}» больше техкарт, в среднем на {num(f['median_pct'])}% при допуске "
        f"{num(f['allowance_pct'])}%{period}. Предлагаем увеличить норму во всех техкартах на "
        f"{num(f['raise_pct'])}%: кухня, которая работает как "
        "обычно, останется в допуске."
        + (
            f" Себестоимость продаж на бумаге вырастет на ≈ {rub(Decimal(f['month_cost']))} в месяц — это "
            "расход, который уже есть."
            if f["month_cost"] is not None
            else ""
        )
        + " Норму меняет "
        "шеф-технолог в "
        "учетной системе; после выгрузки техкарт находка пересчитается."
    )
    return title, text, items


VERDICTS = {
    "confirmed": "эффект подтвержден",
    "inconclusive": "эффект не доказан — разница могла быть случайной",
    "rejected": "изменение не сработало",
}


def check_watch(f: dict[str, Any]) -> tuple[str, str, list[str]]:
    if f["state"] == "done":
        title = f"Итог проверки «{f['title']}»"
        effect = ""
        if f["effect"] is not None:
            effect = f" Эффект ≈ {rub(Decimal(f['effect']))} в месяц"
            if f["ci_low"] is not None and f["ci_high"] is not None:
                effect += f" (от {rub(Decimal(f['ci_low']))} до {rub(Decimal(f['ci_high']))})"
            effect += "."
        text = (
            f"Проверка «{f['title']}» ({_ddmm(f['starts_on'])}–{_ddmm(f['ends_on'])}) закончилась: "
            f"{VERDICTS.get(f['verdict'], f['verdict'])}.{effect} Что делать дальше, решает УК на экране "
            "проверки."
        )
        return title, text, []
    items = [
        f"{x['restaurant']}: продажи выгружены только по {_ddmm(x['last'])}, данные сети — по "
        f"{_ddmm(f['data_to'])}"
        if x["last"]
        else f"{x['restaurant']}: продаж за время проверки нет"
        for x in f["stopped"]
    ]
    items += [
        f"{x['restaurant']}: с {_ddmm(x['since'])} товар берут у нового поставщика «{x['supplier']}» — цена "
        "или фасовка могли измениться"
        for x in f["new_suppliers"]
    ]
    items += [f"{_ddmm(d)} — праздник: гости и кухня в этот день работают иначе" for d in f["holidays"]]
    title = f"Проверка «{f['title']}»: день {f['day']} из {f['days']}"
    who = f"в проверке — {', '.join(f['test'])}"
    if f["control"]:
        who += f", для сравнения — {', '.join(f['control'])}"
    progress = f["progress"] or "Промежуточного замера еще нет."
    risks = "Что может помешать — в списке ниже." if items else "Помех в данных не видно."
    text = f"Проверка идет с {_ddmm(f['starts_on'])} по {_ddmm(f['ends_on'])}, {who}. {progress} {risks}"
    return title, text, items


RULES = {
    Agent.INVENTORY_PREP: inventory,
    Agent.TASK_DUE: task_due,
    Agent.TASK_STUCK: task_stuck,
    Agent.DATA_CHECK: data_check,
    Agent.SUPPLIER_CLAIM: supplier_claim,
    Agent.TRANSFER: transfer,
    Agent.HQ_AGENDA: hq_agenda,
    Agent.SHORTAGE_STORY: shortage_story,
    Agent.SUPPLIER_DEAL: supplier_deal,
    Agent.RECIPE_UPDATE: recipe_update,
    Agent.CHECK_WATCH: check_watch,
}


def by_rules(agent: str, facts: dict[str, Any]) -> tuple[str, str, list[str]]:
    return RULES[Agent(agent)](facts)
