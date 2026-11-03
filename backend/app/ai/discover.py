"""Ideas of new findings (ADR 0008, stage 5.5): the assistant looks at aggregates — never raw rows — and
proposes patterns the engine has no rule for, like «в R07 по понедельникам списывают хлеб».

The code builds the aggregates (each row with an id), the model proposes up to five ideas, each pointing at
the rows it rests on; the code checks that the rows exist and that every number of the idea is in them. An
analyst accepts or rejects each idea; an accepted one goes to «Идеи находок» of the project's workspace, and
only then is a deterministic rule written for it, with a test (the engine never runs the model's words). For
the HQ only.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.ai.gateway import Gateway
from app.ai.models import AiSuggestion
from app.ai.suggestions import Proposal, ask, keep, out
from app.ai.tools import pct
from app.ai.verify import unsupported
from app.catalog.models import Product
from app.core import words
from app.core.errors import ForbiddenError
from app.operations.models import Sale, WriteOff
from app.tenancy.context import AccessContext, user_session
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

WEEKS = 8
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAY_SHARE = Decimal("0.25")  # one weekday holds a quarter of a week's write-offs (even: 14,3 %)
ABOVE_NETWORK = Decimal("1.5")  # write-offs per revenue 1,5 times the network's
MAX_ROWS = 40
MIN_DAYS = 4  # days with write-offs of a product in the period: fewer is noise


class Idea(BaseModel):
    title: str = Field(description="Коротко, как заголовок находки")
    pattern: str = Field(description="Что повторяется — по строкам агрегатов")
    rows: list[str] = Field(description="id строк агрегатов, на которых держится идея")
    why_it_matters: str = Field(description="Чем это грозит ресторану")
    rule_sketch: str = Field(description="Как такое правило мог бы проверять код")


class Ideas(BaseModel):
    ideas: list[Idea] = Field(description="Не больше пяти, самые сильные первыми")


def _may(ctx: AccessContext) -> None:
    if not ctx.can(Permission.FINDINGS_REVIEW):
        raise ForbiddenError("Идеи новых находок — для управляющей компании")


def aggregates(session: Session, today: date) -> dict[str, list[dict[str, Any]]]:
    """Where write-offs pile up: by weekday within a restaurant and product, and against the network. By
    product, not category: a category mixes kilos and pieces (code review 02.11.2026, p. 11). Rows are
    sorted by the strength of the signal before the list is cut, each carries its words for the screen."""
    since = today - timedelta(weeks=WEEKS)
    codes = {rid: code for rid, code in session.execute(select(Restaurant.id, Restaurant.code)).all()}
    weekday = extract("isodow", WriteOff.day)
    rows = session.execute(
        select(
            WriteOff.restaurant_id,
            Product.name,
            weekday,
            func.sum(WriteOff.qty),
            func.count(func.distinct(WriteOff.day)),
        )
        .join(Product, Product.id == WriteOff.product_id)
        .where(WriteOff.day > since, WriteOff.day <= today)
        .group_by(WriteOff.restaurant_id, Product.name, weekday)
    ).all()
    week: dict[tuple[UUID, str], dict[int, Decimal]] = defaultdict(dict)
    days_with: dict[tuple[UUID, str], int] = defaultdict(int)
    for rid, product, dow, qty, n in rows:
        week[(rid, product)][int(dow)] = qty
        days_with[(rid, product)] += n
    strong: list[tuple[Decimal, dict[str, Any]]] = []
    for (rid, product), days in week.items():
        total = sum(days.values(), Decimal(0))
        if not total or days_with[(rid, product)] < MIN_DAYS:
            continue  # a few write-offs make any weekday look special
        dow, qty = max(days.items(), key=lambda kv: kv[1])
        if qty / total >= WEEKDAY_SHARE:
            code, share = codes.get(rid), pct(qty / total)
            strong.append(
                (
                    qty / total,
                    {
                        "restaurant": code,
                        "product": product,
                        "weekday": WEEKDAYS[dow - 1],
                        "share_of_week": share,
                        "text": f"{code} · {product}: {share} списаний недели — {WEEKDAYS[dow - 1]}",
                    },
                )
            )
    by_weekday = [row for _, row in sorted(strong, key=lambda x: -x[0])]

    sold = select(Sale.restaurant_id, func.sum(Sale.revenue)).where(Sale.day > since, Sale.day <= today)
    revenue = {rid: total for rid, total in session.execute(sold.group_by(Sale.restaurant_id)).all()}
    per_product: dict[str, dict[UUID, Decimal]] = defaultdict(dict)
    for (rid, product), days in week.items():
        if revenue.get(rid):
            per_product[product][rid] = sum(days.values(), Decimal(0)) / revenue[rid] * 1000
    above: list[tuple[Decimal, dict[str, Any]]] = []
    for product, places in per_product.items():
        if len(places) < 3:
            continue
        mean = sum(places.values(), Decimal(0)) / len(places)
        for rid, value in places.items():
            if mean and value / mean >= ABOVE_NETWORK:
                mine, net = words.number(value, 2), words.number(mean, 2)
                above.append(
                    (
                        value / mean,
                        {
                            "restaurant": codes.get(rid),
                            "product": product,
                            "write_offs_per_1000_rub_revenue": mine,
                            "network_average": net,
                            "text": f"{codes.get(rid)} · {product}: списания {mine} на 1000 ₽ выручки, "
                            f"в среднем по сети {net}",
                        },
                    )
                )
    vs_network = [row for _, row in sorted(above, key=lambda x: -x[0])]
    table = {"write_offs_by_weekday": by_weekday[:MAX_ROWS], "write_offs_vs_network": vs_network[:MAX_ROWS]}
    n = 0
    for name, items in table.items():
        for item in items:
            n += 1
            item["id"] = f"a{n}"
            item["table"] = name
    return table


def _rows_and_numbers(table: dict[str, list[dict[str, Any]]]) -> Any:
    by_id = {row["id"]: row for items in table.values() for row in items}

    def check(ideas: Ideas) -> list[str]:
        problems = []
        if len(ideas.ideas) > 5:
            problems.append("идей больше пяти")
        for idea in ideas.ideas:
            missing = [r for r in idea.rows if r not in by_id]
            if not idea.rows or missing:
                problems.append(f"«{idea.title}»: нет строк {', '.join(missing) or '—'}")
                continue
            # Every number of an idea must be in the rows it points at, not just somewhere in the table. The
            # rule's sketch proposes thresholds for a developer — a proposal, not a fact (code review
            # 02.11.2026, p. 9); the screen says so.
            text = " ".join([idea.title, idea.pattern, idea.why_it_matters])
            problems += [f"«{idea.title}»: {n}" for n in unsupported(text, [by_id[r] for r in idea.rows])]
        return problems

    return check


def propose_ideas(gateway: Gateway, ctx: AccessContext, today: date) -> list[Proposal]:
    _may(ctx)
    with user_session(ctx) as session:
        table = aggregates(session, today)
    basis = {"period_weeks": WEEKS, **table}
    result, chat = ask(
        gateway,
        ctx,
        task="discover",
        prompt_name="discover",
        basis=basis,
        answer=Ideas,
        check=_rows_and_numbers(table),
        facts_of=lambda r: [i.model_dump(exclude={"rule_sketch"}) for i in r.ideas],
    )
    # One row per idea: the analyst decides on each. The rows an idea rests on are kept with it.
    by_id = {row["id"]: row for items in table.values() for row in items}
    contents = [{**i.model_dump(mode="json"), "evidence": [by_id[r] for r in i.rows]} for i in result.ideas]
    return keep(
        ctx,
        kind="finding_idea",
        subject_id=None,
        restaurant_id=None,
        contents=contents,
        basis=basis,
        chat=chat,
    )


def ideas(ctx: AccessContext) -> list[Proposal]:
    """The batches of ideas, the latest first, decided ones too — all of them (Q21, 03.11.2026: «пока храним и
    показываем всё»)."""
    _may(ctx)
    with user_session(ctx) as s:
        rows = s.execute(
            select(AiSuggestion)
            .where(AiSuggestion.kind == "finding_idea", AiSuggestion.status != "superseded")
            .order_by(AiSuggestion.created_at.desc())
        ).scalars()
        return [out(r) for r in rows]
