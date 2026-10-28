"""The assistant's tools (docs/08, «Как устроен»): thin wrappers over the services, never SQL of their own.

Each call:
- validates its arguments against the tool's schema (the model's arguments are untrusted input);
- runs in its own short read-only transaction under the asking user's row-level security
  (`tenancy.tool_session`), with the role read again from the database;
- refuses a tool the role may not use (`compare_restaurants` — only who may compare restaurants);
- returns figures already formatted («12 400 ₽», «31,2%»): the model copies them and computes nothing
  (CLAUDE.md, principle 1), and the chat checks every number of the answer against these results.

A director's tools see their restaurant and the network's average, never another restaurant by name: the
findings come through `insights.visible`, other rows through RLS. Every tool has an isolation test
(tests/test_ai_tools.py walks the registry).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import Product, Supplier
from app.core import words
from app.core.errors import NotFoundError
from app.experiments.models import Experiment
from app.insights.models import ReviewStatus
from app.insights.visible import VisibleFinding, visible_finding, visible_findings
from app.operations.models import Receipt
from app.overview import service as overview
from app.overview.models import KpiSnapshot
from app.tasks.models import Task, TaskStatus
from app.tenancy.context import AccessContext, tool_session
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission

log = logging.getLogger(__name__)
Result = dict[str, Any]
LIMIT = 20  # rows per answer: the model reads them all, so lists stay short


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{words.number(value, 0)} ₽"


def price(value: Decimal) -> str:
    return f"{words.number(value, 2)} ₽"


def pct(share: Decimal | None, places: int = 1) -> str | None:
    return None if share is None else words.percent(share, places)


def day(value: date | None) -> str | None:
    return None if value is None else f"{value:%d.%m.%Y}"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class FindingsArgs(Args):
    process: (
        Literal[
            "purchasing",
            "receiving",
            "storage",
            "production",
            "writeoffs",
            "inventory",
            "accounting",
            "planning",
        ]
        | None
    ) = Field(
        None,
        description="Процесс: закупка, приемка, хранение, производство (ТТК), списания, инвентаризация, учет "
        "и данные, планирование запасов",
    )
    restaurant_code: str | None = Field(None, description="Код ресторана, например R01; только для УК")


class FindingArgs(Args):
    finding_id: UUID = Field(description="id находки из get_findings")


class ProductArgs(Args):
    query: str = Field(min_length=2, max_length=100, description="Часть названия товара")


class PricesArgs(Args):
    product: str = Field(min_length=2, max_length=100, description="Название товара или его часть")
    days: int = Field(30, ge=7, le=180, description="За сколько последних дней")


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    args: type[Args]
    run: Callable[[Session, AccessContext, Any, date], Result]
    permission: Permission | None = None

    def schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        return {"name": self.name, "description": self.description, "input_schema": schema}


# ------------------------------------------------------------------ the tools


def _places(session: Session) -> dict[UUID, Restaurant]:
    """The restaurants this user may see: a director — their own."""
    return {r.id: r for r in session.execute(select(Restaurant).order_by(Restaurant.code)).scalars()}


def _kpis(row: KpiSnapshot | None) -> Result | None:
    if row is None:
        return None
    return {
        "food_cost_actual": pct(row.food_cost_actual),
        "food_cost_theory": pct(row.food_cost_theory),
        "food_cost_period": f"{day(row.food_cost_from)}–{day(row.food_cost_to)}"
        if row.food_cost_from
        else None,
        "write_offs_share_of_revenue": pct(row.write_offs_share, 2),
        "write_offs_period": f"{day(row.write_offs_from)}–{day(row.write_offs_to)}"
        if row.write_offs_from
        else None,
        "revenue": money(row.revenue),
    }


def get_kpis(session: Session, ctx: AccessContext, _: NoArgs, today: date) -> Result:
    places = _places(session)
    snapshots = {k.restaurant_id: k for k in session.execute(select(KpiSnapshot)).scalars()}
    return {
        "restaurants": [
            {"code": r.code, "name": r.name, **(_kpis(snapshots.get(r.id)) or {"no_data": True})}
            for r in places.values()
        ],
        "network_average": _kpis(snapshots.get(None)),
        "note": "Фудкост — за период между последними инвентаризациями; среднее по сети взвешено по выручке",
    }


def _finding(f: VisibleFinding, *, full: bool = False) -> Result:
    out: Result = {
        "id": str(f.id),
        "title": f.title,
        "restaurant": f.restaurant_name or "вся сеть",
        "process": overview.PROCESS_TITLE.get(f.process, f.process),
        "effect_per_month": money(f.effect_rub_month),
        "stage": f.work.stage,
    }
    if full:
        view = f.view or {}
        out |= {
            "headline": f.headline,
            "summary": view.get("summary"),
            "causes": view.get("causes") or [],
            "actions": f.actions,
            "effect_note": f.effect_note,
            "period": f"{day(f.period_from)}–{day(f.period_to)}" if f.period_from else None,
            "confidence": f.confidence,
            "tasks_late": f.work.tasks_late,
        }
    return out


def get_findings(session: Session, ctx: AccessContext, args: FindingsArgs, today: date) -> Result:
    restaurant_id = None
    if args.restaurant_code:
        match = [r for r in _places(session).values() if r.code == args.restaurant_code]
        if not match:
            return {
                "error": "Ресторан с таким кодом не найден или недоступен"
            }  # the argument is not repeated
        restaurant_id = match[0].id
    items = [
        f
        for f in visible_findings(session, ctx, today=today, restaurant_id=restaurant_id)
        if f.status in overview.OPEN and (args.process is None or f.process == args.process)
    ]
    return {"total": len(items), "findings": [_finding(f) for f in items[:LIMIT]]}


def explain_finding(session: Session, ctx: AccessContext, args: FindingArgs, today: date) -> Result:
    try:
        f = visible_finding(session, ctx, args.finding_id, today=today)
    except NotFoundError:
        f = None
    if f is None or f.review_status not in (None, ReviewStatus.CONFIRMED):  # under review: not discussed
        return {"error": "Находка не найдена или недоступна"}
    return _finding(f, full=True)


def compare_restaurants(session: Session, ctx: AccessContext, _: NoArgs, today: date) -> Result:
    return {
        "restaurants": [
            {
                "code": r.code,
                "name": r.name,
                "losses_per_month": money(r.losses),
                "potential_per_month": money(r.potential),
                "food_cost_actual": pct(r.food_cost),
                "tasks_late": r.late,
                "tasks_done": f"{r.tasks_done} из {r.tasks_total}",
                "stale_data": r.stale_data,
            }
            for r in overview.restaurants(session, today)
        ]
    }


def get_tasks(session: Session, ctx: AccessContext, _: NoArgs, today: date) -> Result:
    places = _places(session)
    tasks = list(
        session.execute(select(Task).where(Task.status != TaskStatus.DONE).order_by(Task.due_on)).scalars()
    )
    return {
        "open": len(tasks),
        "late": sum(1 for t in tasks if t.due_on < today),
        "tasks": [
            {
                "title": t.title,
                "restaurant": places[t.restaurant_id].name if t.restaurant_id in places else None,
                "status": "просрочена"
                if t.due_on < today
                else ("в работе" if t.status == "in_progress" else "назначена"),
                "due": day(t.due_on),
            }
            for t in tasks[:LIMIT]
        ],
    }


def get_checks(session: Session, ctx: AccessContext, _: NoArgs, today: date) -> Result:
    places = _places(session)
    checks = list(session.execute(select(Experiment).order_by(Experiment.starts_on.desc())).scalars())
    return {
        "checks": [
            {
                "title": c.title,
                "status": c.status,
                "verdict": c.verdict,
                "expected_per_month": money(c.expected_rub_month),
                "effect_per_month": money(c.effect_rub_month),
                "period": f"{day(c.starts_on)}–{day(c.ends_on)}",
                # Only the restaurants this user may see; another restaurant's id never leaves the server.
                "my_restaurants_in_test": [places[r].name for r in c.test_restaurant_ids if r in places],
                "result": c.result_text,
            }
            for c in checks[:LIMIT]
        ]
    }


def search_products(session: Session, ctx: AccessContext, args: ProductArgs, today: date) -> Result:
    rows = session.execute(
        select(Product.name, Product.base_unit)
        .where(Product.name.ilike(f"%{_like(args.query)}%"))
        .order_by(Product.name)
        .limit(LIMIT)
    ).all()
    return {"products": [{"name": n, "unit": str(u)} for n, u in rows]}


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_purchase_prices(session: Session, ctx: AccessContext, args: PricesArgs, today: date) -> Result:
    since = today - timedelta(days=args.days)
    places = _places(session)
    rows = session.execute(
        select(
            Product.name,
            Product.base_unit,
            Supplier.name,
            Receipt.restaurant_id,
            func.sum(Receipt.amount),
            func.sum(Receipt.qty),
        )
        .join(Product, Product.id == Receipt.product_id)
        .outerjoin(Supplier, Supplier.id == Receipt.supplier_id)
        .where(Product.name.ilike(f"%{_like(args.product)}%"), Receipt.day > since, Receipt.day <= today)
        .group_by(Product.name, Product.base_unit, Supplier.name, Receipt.restaurant_id)
        .order_by(Product.name, Supplier.name)
        .limit(LIMIT)
    ).all()
    return {
        "period": f"{day(since + timedelta(days=1))}–{day(today)}",
        "prices": [
            {
                "product": p,
                "supplier": s or "не указан",
                "restaurant": places[r].name if r in places else None,
                "avg_price_per_unit": price(amount / qty) + f" за {u}",
                "bought": f"{words.number(qty, 1)} {u}",
                "amount": money(amount),
            }
            for p, u, s, r, amount, qty in rows
        ],
    }


TOOLS: dict[str, ToolDef] = {
    t.name: t
    for t in [
        ToolDef(
            "get_kpis",
            "Фудкост (факт и по техкартам), доля списаний в выручке и выручка: по ресторанам, которые видит "
            "пользователь, и среднее по сети.",
            NoArgs,
            get_kpis,
        ),
        ToolDef(
            "get_findings",
            "Открытые находки (потери и возможности) с эффектом в рублях в месяц, самые дорогие первыми. "
            "Можно отфильтровать по процессу и ресторану.",
            FindingsArgs,
            get_findings,
        ),
        ToolDef(
            "explain_finding",
            "Подробно об одной находке: суть, вероятные причины, что сделать, период, уверенность.",
            FindingArgs,
            explain_finding,
        ),
        ToolDef(
            "compare_restaurants",
            "Сравнение ресторанов сети по имени: потери, потенциал, фудкост, просроченные задачи, свежесть "
            "данных. Только для управляющей компании.",
            NoArgs,
            compare_restaurants,
            Permission.NETWORK_COMPARE,
        ),
        ToolDef("get_tasks", "Открытые задачи: что, где, срок, просрочена ли.", NoArgs, get_tasks),
        ToolDef(
            "get_checks",
            "Проверки изменений: статус, итог, ожидаемый и подтвержденный эффект в рублях в месяц.",
            NoArgs,
            get_checks,
        ),
        ToolDef(
            "search_products", "Поиск товара в справочнике по части названия.", ProductArgs, search_products
        ),
        ToolDef(
            "get_purchase_prices",
            "Средняя цена закупки товара по поставщикам и ресторанам за последние дни, из накладных.",
            PricesArgs,
            get_purchase_prices,
        ),
    ]
}


def schemas(ctx: AccessContext) -> list[dict[str, Any]]:
    """The tools this user may call, in a fixed order (a stable prefix for prompt caching)."""
    return [t.schema() for t in TOOLS.values() if t.permission is None or ctx.can(t.permission)]


def run(name: str, arguments: Any, *, user_id: UUID, tenant_id: UUID, today: date) -> tuple[Result, bool]:
    """One tool call → (result, is_error). Errors are answers for the model, not exceptions: it should say
    what it could not find rather than stop the conversation."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Нет инструмента {name}"}, True
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        # Which fields are wrong, not what was in them: an error repeats no figure of the model's own.
        fields = sorted({".".join(map(str, e["loc"])) or "arguments" for e in exc.errors()})
        return {"error": "Неверные аргументы", "fields": fields}, True
    try:
        with tool_session(user_id, tenant_id) as (session, ctx):
            if tool.permission is not None and not ctx.can(tool.permission):
                return {"error": "Эти данные пользователю недоступны"}, True
            result = tool.run(session, ctx, args, today)
    except PermissionError:
        return {"error": "Пользователь не найден или отключен"}, True
    except Exception:  # a tool that failed is an answer for the model too, not a failed question
        log.exception("tool %s failed", name)
        return {"error": "Не удалось получить данные"}, True
    return result, "error" in result
