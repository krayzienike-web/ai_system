"""How a finding is shown (ADR 0007): the screens draw these blocks as they are and compute nothing.

Built from a draft's evidence, so every figure is one the detector computed:
- `summary`, `causes`, `confidence_note`, `metric` — the words and the one number that matter;
- `scale` — «me / network / norm» on one scale, with the answer to «Это много?» in words;
- `composition` — what the used quantity consists of (M1);
- `chart` — the figure by period (M1);
- `table` — the documents behind the figure («Откуда цифры»).
Values are display numbers (percent points, rubles, base units) rounded for reading.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.analytics.drafts import Draft
from app.analytics.facts import Facts

UNIT = {"kg": "кг", "l": "л", "pcs": "шт"}

CAUSES = {
    "M1": [
        "Порции на раздаче больше, чем в техкарте",
        "Выход при обработке ниже заложенного в техкарте",
        "Часть списаний не оформлена документом",
    ],
    "M1:under": [
        "На раздаче кладут меньше, чем в техкарте",
        "Часть прихода или перемещений не проведена документами",
        "Товар заменяют другим (пересорт), или техкарта завышена",
    ],
    "M1:net": [
        "Техкарта не соответствует продукту, который сейчас закупается",
        "Выход при обработке изменился, а техкарту не обновили",
    ],
    "M2": [
        "Подорожали ингредиенты, а цена в меню прежняя",
        "Цены в меню меняются только с новым меню: до него помогают поставщик и техкарта",
    ],
    "M3": [
        "Заказ у другого поставщика, чем у остальных ресторанов",
        "Срочные заказы по более высокой цене",
        "Поставщик возит в этот ресторан другую позицию того же товара (например, другой жирности или "
        "калибра), а в справочнике они сведены в одну: проверьте синхронизацию номенклатуры",
    ],
    "M7:no_recipe": ["Блюдо ввели в меню, а техкарту в iiko не завели или не загрузили"],
    "M7:gap": [
        "Выгрузку забыли сделать или загрузить",
        "Выгрузка из учетной системы упала с ошибкой",
    ],
    "M3:contract": ["Поставщик выставляет цену выше договорной"],
    "M3:growth": ["Поставщик поднял цену для всей сети"],
}


def _n(value: Decimal | str | None, places: int = 1) -> float | None:
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


def _pp(share: str | Decimal | None) -> float | None:
    """0.0915 → 9.2 (percent)."""
    return None if share is None else _n(Decimal(share) * 100)


def _points(value: float) -> str:
    """1 пункт, 2 пункта, 5 пунктов, 1,5 пункта."""
    v = round(abs(value), 1)
    if v != int(v):
        return f"{_ru(v, '').strip()} пункта"
    n = int(v)
    form = (
        "пункт"
        if n % 10 == 1 and n % 100 != 11
        else "пункта"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
        else "пунктов"
    )
    return f"{n} {form}"


def _ru(value: float, unit: str) -> str:
    text = f"{value:,.1f}".replace(",", " ").replace(".", ",").removesuffix(",0")
    return f"{text}%" if unit == "%" else f"{text} {unit}"


def scale_answer(s: dict[str, Any]) -> str | None:
    """«Это много?» in words: how far the restaurant is from the network (or the norm), and which way."""
    ref, ref_name = (s["network"], (s.get("network_label") or "среднее по сети").lower())
    if ref is None:
        ref, ref_name = s.get("norm"), s.get("norm_label") or "норма"
    if ref is None or not ref:
        return None
    me = s["me"]
    worse = me > ref if s["lower_is_better"] else me < ref
    ratio = me / ref
    if s["unit"] == "%":
        diff = f"на {_points(me - ref)}"
    elif ratio >= 1.5:
        diff = f"в {_ru(ratio, '').strip()} раза"
    else:
        diff = f"на {round(abs(ratio - 1) * 100)}%"
    direction = ("выше" if s["lower_is_better"] else "ниже") if worse else "лучше"
    tail = (
        f", при норме {_ru(s['norm'], s['unit'])}"
        if s.get("norm") is not None and s["network"] is not None
        else ""
    )
    return f"{'Да' if worse else 'Нет'}. {s['label']}: {diff} {direction}, чем {ref_name}{tail}."


def _scale(**kw: Any) -> dict[str, Any]:
    s = {"network": None, "network_label": None, "norm": None, "norm_label": None, **kw}
    s["answer"] = scale_answer(s)
    return s


def _m1(d: Draft, facts: Facts) -> dict[str, Any]:
    ev = d.evidence
    product = next(p for p in facts.products.values() if p.code == ev["product"])
    unit = UNIT.get(product.unit, product.unit)
    if d.restaurant is None:  # the recipe looks wrong across the network
        shares = {code: _pp(s) for code, s in sorted(ev["restaurants"].items())}
        return {
            "summary": d.headline,
            "causes": CAUSES["M1:net"],
            "confidence_note": f"Инвентаризации и продажи {len(shares)} ресторанов за один период",
            "metric": {
                "label": "Расход сверх техкарты, медиана по сети",
                "value": _ru(_pp(ev["median_share"]) or 0, "%"),
                "benchmark": f"допуск {_ru(_pp(ev['allowance']) or 0, '%')}",
            },
            "scale": _scale(
                label="Расход сверх техкарты в среднем по сети",
                unit="%",
                me=_pp(ev["median_share"]),
                norm=_pp(ev["allowance"]),
                lower_is_better=True,
            ),
            "table": {
                "title": "Расход сверх техкарты по ресторанам",
                "columns": ["Ресторан", "Сверх техкарты, %"],
                "rows": [[facts.restaurant_names.get(code, code), share] for code, share in shares.items()],
            },
        }
    periods = ev["periods"]
    last = periods[-1]
    theory, actual, written = (Decimal(last[k]) for k in ("theory", "actual", "write_off"))
    unexplained = actual - theory - written
    network = _pp(last.get("network_share"))
    labels = [f"{p['from'][8:10]}.{p['from'][5:7]}–{p['to'][8:10]}.{p['to'][5:7]}" for p in periods]
    if ev.get("direction") == "under":
        return _m1_under(d, product.name, unit, periods, labels, theory, actual, written, network)
    composition = {
        "unit": unit,
        "formula": "Израсходовано = остаток на начало + приходы ± перемещения − остаток на конец",
        "parts": [
            {"label": "По техкартам проданных блюд", "value": _n(theory), "tone": "brand"},
            {"label": "Списано по документам", "value": _n(written), "tone": "neutral"},
            {"label": "Ничем не объяснено", "value": _n(unexplained), "tone": "loss"},
        ],
    }
    composition["answer"] = (
        f"Из израсходованных {_ru(_n(actual) or 0, unit)} по техкартам ушло {_ru(_n(theory) or 0, unit)}, "
        f"но {_ru(_n(unexplained) or 0, unit)} ничем не объяснены."
    )
    return {
        "summary": d.headline,
        "causes": CAUSES["M1"],
        "confidence_note": (
            f"{len(periods) + 1} инвентаризации, продажи и закупки за {len(periods)} "
            f"{'период' if len(periods) == 1 else 'периода' if len(periods) < 5 else 'периодов'}"
        ),
        "metric": {
            "label": "Расход сверх техкарты",
            "value": _ru(_pp(last["share"]) or 0, "%"),
            "benchmark": f"сеть {_ru(network, '%')}" if network is not None else "сеть —",
            "norm": f"допуск {_ru(_pp(ev['allowance']) or 0, '%')}",
        },
        "scale": _scale(
            label="Расход сверх техкарты",
            unit="%",
            me=_pp(last["share"]),
            network=network,
            norm=_pp(ev["allowance"]),
            lower_is_better=True,
        ),
        "composition": composition,
        "chart": {
            "title": "Расход сверх техкарты по периодам между инвентаризациями",
            "conclusion": d.headline.split(". ")[1] if ". Растет" in d.headline else None,
            "unit": "%",
            "labels": labels,
            "restaurant": [_pp(p["share"]) for p in periods],
            "network_avg": [_pp(p.get("network_share")) for p in periods],
            "norm": _pp(ev["allowance"]),
            "norm_label": "допуск",
        },
        "table": {
            "title": f"{product.name}: расход по периодам, {unit}",
            "columns": ["Период", "По техкартам", "Израсходовано", "Списано", "Сверх техкарты, %"],
            "rows": [
                [label, _n(p["theory"]), _n(p["actual"]), _n(p["write_off"]), _pp(p["share"])]
                for label, p in zip(labels, periods, strict=True)
            ],
        },
    }


def _m1_under(
    d: Draft,
    name: str,
    unit: str,
    periods: list[dict[str, Any]],
    labels: list[str],
    theory: Decimal,
    actual: Decimal,
    written: Decimal,
    network: float | None,
) -> dict[str, Any]:
    short = theory + written - actual
    me = _pp(periods[-1]["share"])
    return {
        "summary": d.headline,
        "causes": CAUSES["M1:under"],
        "confidence_note": (
            f"{len(periods) + 1} инвентаризации, продажи и закупки за {len(periods)} "
            f"{'период' if len(periods) == 1 else 'периода' if len(periods) < 5 else 'периодов'}"
        ),
        "metric": {
            "label": "Расход меньше техкарты",
            "value": _ru(abs(me or 0), "%"),
            "benchmark": f"сеть {_ru(network, '%')}" if network is not None else "сеть —",
            "norm": f"порог −{_ru(_pp(d.evidence['under']) or 0, '%')}",
        },
        "scale": _scale(
            label="Расход относительно техкарты",
            unit="%",
            me=me,
            network=network,
            lower_is_better=False,
        ),
        "composition": {
            "unit": unit,
            "formula": "Израсходовано = остаток на начало + приходы ± перемещения − остаток на конец",
            "parts": [
                {"label": "Израсходовано", "value": _n(actual), "tone": "brand"},
                {"label": "Списано по документам", "value": _n(written), "tone": "neutral"},
                {"label": "Не хватает до техкарты", "value": _n(short), "tone": "loss"},
            ],
            "answer": (
                f"По техкартам проданных блюд должно было уйти {_ru(_n(theory) or 0, unit)}, "
                f"а израсходовано и списано {_ru(_n(actual + written) or 0, unit)}: "
                f"на {_ru(_n(short) or 0, unit)} меньше."
            ),
        },
        "chart": {
            "title": "Расход относительно техкарты по периодам между инвентаризациями",
            "conclusion": None,
            "unit": "%",
            "labels": labels,
            "restaurant": [_pp(p["share"]) for p in periods],
            "network_avg": [_pp(p.get("network_share")) for p in periods],
            "norm": 0.0,
            "norm_label": "техкарта",
        },
        "table": {
            "title": f"{name}: расход по периодам, {unit}",
            "columns": ["Период", "По техкартам", "Израсходовано", "Списано", "Относительно техкарты, %"],
            "rows": [
                [label, _n(p["theory"]), _n(p["actual"]), _n(p["write_off"]), _pp(p["share"])]
                for label, p in zip(labels, periods, strict=True)
            ],
        },
    }


def _m2(d: Draft, facts: Facts) -> dict[str, Any]:
    ev = d.evidence
    codes = {p.code: p for p in facts.products.values()}
    return {
        "summary": d.headline,
        "causes": CAUSES["M2"],
        "confidence_note": "Закупки сети за 4 недели, техкарта блюда и продажи",
        "metric": {
            "label": "Фудкост блюда",
            "value": _ru(_pp(ev["food_cost"]) or 0, "%"),
            "benchmark": f"цель {_ru(_pp(ev['target']) or 0, '%')}",
        },
        "scale": _scale(
            label="Фудкост блюда",
            unit="%",
            me=_pp(ev["food_cost"]),
            norm=_pp(ev["target"]),
            norm_label="цель",
            lower_is_better=True,
        ),
        "table": {
            "title": "Себестоимость порции по ингредиентам",
            "columns": ["Ингредиент", "На порцию", "Цена квартал назад, ₽", "Цена сейчас, ₽"],
            "rows": [
                [
                    codes[i["product"]].name if i["product"] in codes else i["product"],
                    _n(i["qty"], 3),
                    _n(i["price_before"], 2),
                    _n(i["price"], 2),
                ]
                for i in ev["ingredients"]
            ],
        },
    }


def _m3(d: Draft, facts: Facts) -> dict[str, Any]:
    ev = d.evidence
    product = next(p for p in facts.products.values() if p.code == ev["product"])
    unit = f"₽/{UNIT.get(product.unit, product.unit)}"
    kind = ev.get("kind")
    if kind == "contract":
        return {
            "summary": d.headline,
            "causes": CAUSES["M3:contract"],
            "confidence_note": f"Договорная цена и {ev['receipts']} накладных",
            "metric": {
                "label": "Цена в накладных",
                "value": f"{ev['paid']} {unit}",
                "benchmark": f"по договору {ev['contract_price']} {unit}",
            },
            "scale": _scale(
                label="Цена закупки",
                unit=unit,
                me=_n(ev["paid"], 2),
                network=_n(ev["contract_price"], 2),
                network_label="Договорная цена",
                lower_is_better=True,
            ),
            "table": {
                "title": "Переплата по ресторанам, ₽",
                "columns": ["Ресторан", "Переплата, ₽"],
                "rows": [
                    [facts.restaurant_names.get(code, code), _n(v, 0)]
                    for code, v in ev["restaurants"].items()
                ],
            },
        }
    if kind == "growth":
        return {
            "summary": d.headline,
            "causes": CAUSES["M3:growth"],
            "confidence_note": f"Закупки {ev['restaurants']} ресторанов за два одинаковых периода",
            "metric": {
                "label": "Цена закупки по сети",
                "value": f"{ev['price']} {unit}",
                "benchmark": f"квартал назад {ev['price_before']} {unit}",
            },
            "scale": _scale(
                label="Цена закупки",
                unit=unit,
                me=_n(ev["price"], 2),
                network=_n(ev["price_before"], 2),
                network_label="Квартал назад",
                lower_is_better=True,
            ),
        }
    return {
        "summary": d.headline,
        "causes": CAUSES["M3"],
        "confidence_note": f"Закупки за {ev['days']} дней по {len(ev['network'])} ресторанам",
        "metric": {
            "label": "Цена закупки",
            "value": f"{ev['price']} {unit}",
            "benchmark": f"сеть {ev['benchmark']} {unit}",
        },
        "scale": _scale(
            label="Цена закупки",
            unit=unit,
            me=_n(ev["price"], 2),
            network=_n(ev["benchmark"], 2),
            network_label="Типичная цена сети",
            lower_is_better=True,
        ),
        "table": {
            "title": f"{product.name}: средняя цена закупки по ресторанам, {unit}",
            "columns": ["Ресторан", f"Цена, {unit}"],
            "rows": [
                [facts.restaurant_names.get(code, code), _n(v, 2)]
                for code, v in sorted(ev["network"].items())
            ],
        },
    }


def _m7(d: Draft, facts: Facts) -> dict[str, Any]:
    ev = d.evidence
    if ev["kind"] == "no_recipe":
        return {
            "summary": d.headline,
            "causes": CAUSES["M7:no_recipe"],
            "confidence_note": "Продажи r_keeper и загруженные техкарты",
            "metric": {
                "label": "Доля выручки сети без техкарты",
                "value": _ru(_pp(ev["revenue_share"]) or 0, "%"),
                "benchmark": f"продается в {len(ev['restaurants'])} ресторанах",
            },
            "table": {
                "title": "Где продается",
                "columns": ["Ресторан"],
                "rows": [[facts.restaurant_names.get(code, code)] for code in ev["restaurants"]],
            },
        }
    last, network_last = ev["last"], ev["network_last"]
    return {
        "summary": d.headline,
        "causes": CAUSES["M7:gap"],
        "confidence_note": "Даты загруженных файлов этого ресторана и сети",
        "metric": {
            "label": "Нет данных",
            "value": f"{ev['gap_days']} дн.",
            "benchmark": f"обычно перерыв {_ru(float(ev['usual_pause_days']), 'дн.')}",
        },
        "table": {
            "title": "Последний загруженный день",
            "columns": ["", "Дата"],
            "rows": [
                ["Этот ресторан", f"{last[8:10]}.{last[5:7]}"],
                ["Другие рестораны", f"{network_last[8:10]}.{network_last[5:7]}"],
            ],
        },
    }


def build(d: Draft, facts: Facts) -> dict[str, Any] | None:
    builder = {"M1": _m1, "M2": _m2, "M3": _m3, "M7": _m7}.get(d.module)
    return builder(d, facts) if builder else None
