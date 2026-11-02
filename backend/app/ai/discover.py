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
    """Where write-offs pile up: by weekday within a restaurant and category, and against the network."""
    since = today - timedelta(weeks=WEEKS)
    codes = {rid: code for rid, code in session.execute(select(Restaurant.id, Restaurant.code)).all()}
    weekday = extract("isodow", WriteOff.day)
    rows = session.execute(
        select(WriteOff.restaurant_id, Product.category, weekday, func.sum(WriteOff.qty))
        .join(Product, Product.id == WriteOff.product_id)
        .where(WriteOff.day > since, WriteOff.day <= today)
        .group_by(WriteOff.restaurant_id, Product.category, weekday)
    ).all()
    week: dict[tuple[UUID, str], dict[int, Decimal]] = defaultdict(dict)
    for rid, category, dow, qty in rows:
        week[(rid, category or "без категории")][int(dow)] = qty
    by_weekday = []
    for (rid, category), days in sorted(week.items(), key=lambda kv: (codes.get(kv[0][0], ""), kv[0][1])):
        total = sum(days.values(), Decimal(0))
        if not total:
            continue
        dow, qty = max(days.items(), key=lambda kv: kv[1])
        if qty / total >= WEEKDAY_SHARE:
            by_weekday.append(
                {
                    "restaurant": codes.get(rid),
                    "category": category,
                    "weekday": WEEKDAYS[dow - 1],
                    "share_of_week": pct(qty / total),
                }
            )

    sold = select(Sale.restaurant_id, func.sum(Sale.revenue)).where(Sale.day > since, Sale.day <= today)
    revenue = {rid: total for rid, total in session.execute(sold.group_by(Sale.restaurant_id)).all()}
    per_cat: dict[str, dict[UUID, Decimal]] = defaultdict(dict)
    for (rid, category), days in week.items():
        if revenue.get(rid):
            per_cat[category][rid] = sum(days.values(), Decimal(0)) / revenue[rid] * 1000
    vs_network = []
    for category, places in sorted(per_cat.items()):
        if len(places) < 3:
            continue
        mean = sum(places.values(), Decimal(0)) / len(places)
        for rid, value in sorted(places.items(), key=lambda kv: codes.get(kv[0], "")):
            if mean and value / mean >= ABOVE_NETWORK:
                vs_network.append(
                    {
                        "restaurant": codes.get(rid),
                        "category": category,
                        "write_offs_per_1000_rub": f"{value:.2f}".replace(".", ","),
                        "network_average": f"{mean:.2f}".replace(".", ","),
                    }
                )
    table = {"write_offs_by_weekday": by_weekday, "write_offs_vs_network": vs_network}
    n = 0
    for name, items in table.items():
        del items[MAX_ROWS:]
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
            # Every number of an idea must be in the rows it points at, not just somewhere in the table.
            text = " ".join([idea.title, idea.pattern, idea.why_it_matters, idea.rule_sketch])
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
    """The batches of ideas, the latest first, decided ones too."""
    _may(ctx)
    with user_session(ctx) as s:
        rows = s.execute(
            select(AiSuggestion)
            .where(AiSuggestion.kind == "finding_idea", AiSuggestion.status != "superseded")
            .order_by(AiSuggestion.created_at.desc())
            .limit(10)
        ).scalars()
        return [out(r) for r in rows]
