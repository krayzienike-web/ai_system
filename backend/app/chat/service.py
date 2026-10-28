"""«Спросить су-шефа» before the LLM is connected: answers by rules, every figure from the data (ADR 0007).

The questions it understands are the ones the screens suggest: food cost, overpaying, write-offs, checks,
a finding in context. A director gets their restaurant and the network's average, never other restaurants.
When the assistant goes through `app/ai/gateway` (ADR 0005), these functions become its tools.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import words
from app.core.errors import NotFoundError
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.insights.models import ReviewStatus
from app.insights.visible import VisibleFinding, visible_finding, visible_findings
from app.overview.models import KpiSnapshot
from app.overview.service import OPEN
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

CHECKS = ("проверка", "проверки", "проверок")
SUGGESTIONS_DIRECTOR = [
    "Почему у меня вырос фудкост?",
    "Где я переплачиваю?",
    "Как снизить списания?",
    "Что закончится до поставки?",
]
SUGGESTIONS_HQ = [
    "Сравни рестораны по фудкосту",
    "Где сеть переплачивает?",
    "Какие проверки сработали?",
    "Что закончится до поставки?",
]


@dataclass
class Answer:
    text: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    source_finding_id: UUID | None = None
    source: str | None = None
    suggestions: list[str] = field(default_factory=list)


def suggestions(ctx: AccessContext) -> list[str]:
    return SUGGESTIONS_HQ if ctx.can(Permission.NETWORK_COMPARE) else SUGGESTIONS_DIRECTOR


def _open(session: Session, ctx: AccessContext, today: date) -> list[VisibleFinding]:
    """Open findings through the one read path: what this user may see of them, and nothing else."""
    return [f for f in visible_findings(session, ctx, today=today) if f.status in OPEN]


def _in_context(
    session: Session, ctx: AccessContext, finding_id: UUID | None, today: date
) -> VisibleFinding | None:
    """The finding the question is about, by the card's rules; one still under review is not discussed."""
    if finding_id is None:
        return None
    try:
        f = visible_finding(session, ctx, finding_id, today=today)
    except NotFoundError:
        return None
    return f if f.review_status in (None, ReviewStatus.CONFIRMED) else None


def answer(
    session: Session, ctx: AccessContext, question: str, today: date, finding_id: UUID | None
) -> Answer:
    q = question.lower()
    hq = ctx.can(Permission.NETWORK_COMPARE)
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}  # what the caller may see
    snapshots = {k.restaurant_id: k for k in session.execute(select(KpiSnapshot)).scalars()}
    name = {rid: r.name for rid, r in places.items()}

    if not hq and re.search(r"сравни|други|соседн|остальн", q):
        own = next((snapshots.get(rid) for rid in places), None)
        net = snapshots.get(None)
        return Answer(
            "Данные других ресторанов вам недоступны — могу сравнить ваш ресторан со средним по сети.",
            ["Показатель", "Ваш ресторан", "Среднее по сети"],
            [
                [
                    "Фудкост факт",
                    words.percent(own.food_cost_actual if own else None),
                    words.percent(net.food_cost_actual if net else None),
                ],
                [
                    "Списания, % выручки",
                    words.percent(own.write_offs_share if own else None, 2),
                    words.percent(net.write_offs_share if net else None, 2),
                ],
            ],
            source="последний период между инвентаризациями",
        )

    finding = _in_context(session, ctx, finding_id, today)
    if finding is not None and "за год" in q and finding.effect_rub_month:
        return Answer(
            f"{words.per_month(finding.effect_rub_month)} — это около "
            f"{words.rub(finding.effect_rub_month * 12)} в год.",
            source_finding_id=finding.id,
        )
    if finding is not None and not re.search(r"фудкост|переплач|законч|дефицит|списан|провер", q):
        view = finding.view or {}
        causes = view.get("causes") or []
        return Answer(
            f"{view.get('summary') or finding.headline}\n\n"
            f"Вероятные причины: {'; '.join(causes) if causes else 'не выявлены'}.\n\n"
            f"Что можно сделать: {'; '.join(finding.actions)}.",
            source_finding_id=finding.id,
            suggestions=["Сколько это в рублях за год?", "С чего начать?"],
        )

    if "фудкост" in q:
        rows = [
            [
                name[rid],
                words.percent(k.food_cost_actual),
                words.percent(k.food_cost_theory),
                f"{words.number(((k.food_cost_actual or 0) - (k.food_cost_theory or 0)) * 100)} п.п.",
            ]
            for rid, k in sorted(snapshots.items(), key=lambda x: name.get(x[0], "") if x[0] else "я")
            if rid is not None and rid in name
        ]
        net = snapshots.get(None)
        if net and not hq:
            rows.append(
                [
                    "Среднее по сети",
                    words.percent(net.food_cost_actual),
                    words.percent(net.food_cost_theory),
                    "—",
                ]
            )
        top = next(
            (f for f in _open(session, ctx, today) if f.process == "production" and f.kind == "problem"),
            None,
        )
        period = (
            f"{net.food_cost_from:%d.%m}–{net.food_cost_to:%d.%m}"
            if net and net.food_cost_from and net.food_cost_to
            else ""
        )
        return Answer(
            f"Фактический фудкост считаем между двумя инвентаризациями ({period}). "
            "Разница с фудкостом по техкартам — "
            "то, что ушло сверх нормы."
            + (
                f" Главный вклад — «{top.title}» ({words.per_month(top.effect_rub_month or 0)})."
                if top
                else ""
            ),
            ["Ресторан", "Фактический", "По техкартам", "Разница"],
            rows,
            source_finding_id=top.id if top else None,
            source="продажи r_keeper, склад iiko, закупки 1С:ERP за период",
        )

    if re.search(r"переплач|цен|поставщ", q):
        items = [f for f in _open(session, ctx, today) if f.process == "purchasing"]
        return Answer(
            f"Нашел {words.plural(len(items), ('позицию', 'позиции', 'позиций'))}, "
            "где закупка дороже, чем у сети или раньше.",
            ["Ресторан", "Что", "Эффект"] if hq else ["Что", "Эффект"],
            [
                ([name.get(f.restaurant_id, "Вся сеть") if f.restaurant_id else "Вся сеть"] if hq else [])
                + [f.title, words.per_month(f.effect_rub_month) if f.effect_rub_month else "—"]
                for f in items
            ],
            source="закупки 1С:ERP за 8 недель",
        )

    if re.search(r"законч|дефицит|запас|хватит", q):
        risks = [f for f in _open(session, ctx, today) if f.module == "M6"]
        if not risks:
            return Answer(
                "По расчету ничего не закончится раньше ближайшей поставки. Прогноз — по остаткам от "
                "последней инвентаризации и расходу по дням недели.",
                suggestions=suggestions(ctx),
            )
        return Answer(
            "Закончится раньше поставки — дозакажите или возьмите у соседнего ресторана:",
            (["Ресторан"] if hq else []) + ["Что", "Под угрозой"],
            [
                ([name.get(f.restaurant_id, "") if f.restaurant_id else "Вся сеть"] if hq else [])
                + [f.headline or f.title, f.effect_note or "—"]
                for f in risks
            ],
            source="остатки по документам и расход за 4 недели",
            source_finding_id=risks[0].id,
        )

    if "списан" in q:
        items = [f for f in _open(session, ctx, today) if f.process in ("writeoffs", "storage")]
        return Answer(
            "Резервы по списаниям — в заказе скоропорта под реальное потребление."
            if items
            else "Списаний выше нормы сейчас не нахожу.",
            ["Что", "Эффект"],
            [
                [
                    (f"{name.get(f.restaurant_id, '')}: " if hq and f.restaurant_id else "") + f.title,
                    words.per_month(f.effect_rub_month) if f.effect_rub_month else "—",
                ]
                for f in items
            ],
            source="акты списания iiko",
        )

    if re.search(r"провер|эксперимент", q):
        if not hq:
            return Answer("Проверки изменений ведет управляющая компания; их задачи — в «Моих задачах».")
        checks = list(session.execute(select(Experiment)).scalars())
        done = [e for e in checks if e.status == ExperimentStatus.COMPLETED]
        worked = [e for e in done if e.verdict == Verdict.CONFIRMED]
        text = f"Завершено {words.plural(len(done), CHECKS)}, сработало {len(worked)}."
        running = sum(1 for e in checks if e.status == ExperimentStatus.RUNNING)
        waiting = sum(1 for e in checks if e.status == ExperimentStatus.PROPOSED)
        text += f" Идет {running}, ждут запуска {waiting}."
        return Answer(
            text,
            ["Проверка", "Итог"],
            [
                [
                    e.title,
                    f"+{words.per_month(e.effect_rub_month)}"
                    if e.verdict == Verdict.CONFIRMED and e.effect_rub_month
                    else "не сработало"
                    if e.verdict == Verdict.REJECTED
                    else "непонятно",
                ]
                for e in done
            ],
            source="раздел «Проверки»",
        )

    return Answer(
        "Пока я отвечаю на вопросы о фудкосте, ценах закупки, списаниях и проверках. "
        "Когда подключим языковую модель, отвечу на любой вопрос по данным в пределах ваших прав.",
        suggestions=suggestions(ctx),
    )
