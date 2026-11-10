"""The demo network's work history: what the prototype shows besides the engine's findings (ADR 0007).

- Work on findings: tasks (open, overdue, done with a report), checks (proposed, running, completed with
  a measured result), as HQ and directors would have left them.

Everything is dated relative to `today` (the demo's «today»), so the demo never goes stale.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import engine
from app.analytics.engine import RunResult
from app.analytics.facts import load_facts
from app.analytics.runs import AnalyticsRun, RunStatus
from app.catalog.models import Product
from app.core.period import last_full_week_end
from app.demo.generator import TOMATO_CHECK_FROM
from app.experiments import design
from app.experiments.models import Experiment
from app.insights.models import Finding, ReviewStatus
from app.overview import trend
from app.tasks.models import Task
from app.tenancy.context import AccessContext

D = Decimal


def work(session: Session, ctx: AccessContext, today: date, analyst: UUID) -> None:
    """Tasks and checks on the findings, as HQ and directors would have left them."""
    tid = ctx.tenant_id
    by_key = {f.key: f for f in session.execute(select(Finding).where(Finding.key.is_not(None))).scalars()}
    rid = {code: restaurant for restaurant, code in load_facts(session).restaurants.items()}

    def day(offset: int) -> date:
        return today + timedelta(days=offset)

    def task(f: Finding | None, restaurant: str, title: str, **kw: Any) -> Task:
        t = Task(
            tenant_id=tid,
            restaurant_id=rid[restaurant],
            finding_id=f.id if f else None,
            title=title,
            assigned_by=kw.pop("assigned_by", "hq"),
            created_on=kw.pop("created_on", day(-10)),
            due_on=kw.pop("due_on", day(4)),
            **kw,
        )
        t.checklist_done = [False] * len(t.checklist or [])
        session.add(t)
        return t

    moz, beef, salmon = by_key["M1:R01:P01"], by_key["M3:R02:P08"], by_key["M1:R03:P09"]
    cream = by_key["M3:R05:P04"]

    # Mozzarella: a running check with a task in R01 — today's run measures it (interim, stage 7).
    running = check(
        session,
        ctx,
        analyst,
        moz,
        title="Контрольное взвешивание сыра",
        hypothesis="Если две недели взвешивать моцареллу на раздаче, перерасход снизится с 11% до 4%.",
        metric="Закуплено моцареллы к расходу по техкартам",
        test="R01",
        controls=["R04", "R05"],
        starts=day(-8),
        ends=day(19),
    )
    # Beef: proposed by the analyst, waits for the admin.
    check(
        session,
        ctx,
        analyst,
        beef,
        title="Плановый заказ говядины",
        hypothesis="Если заказывать говядину заранее у основного поставщика, цена вернется к цене сети.",
        metric="Цена говядины, ₽/кг",
        test="R02",
        controls=["R03", "R06"],
        starts=day(4),
        ends=day(32),
        status="proposed",
    )
    session.flush()
    for f, status in ((moz, "in_experiment"), (salmon, "in_work"), (cream, "in_work")):
        f.status = status
    # The tomato check of the history (`history_checks`) worked: HQ closed the finding when it was measured.
    tomato_check = session.execute(
        select(Experiment).where(Experiment.title == TOMATO_TITLE)
    ).scalar_one_or_none()
    if tomato_check is not None and tomato_check.verdict == "confirmed" and tomato_check.finding_id:
        tomatoes = session.get(Finding, tomato_check.finding_id)
        if tomatoes is not None:
            tomatoes.status, tomatoes.resolved_on = "resolved", tomato_check.completed_on

    task(
        moz,
        "R01",
        running.title,
        experiment_id=running.id,
        created_on=day(-8),
        due_on=day(19),
        status="in_progress",
        checklist=["Весы на станции пиццы", "Пересчет моцареллы каждый понедельник"],
    )
    task(
        salmon,
        "R03",
        "Проверить выход филе при разделке",  # set by the HQ: a finding's task is its decision (ADR 0009)
        created_on=day(-9),
        due_on=day(-3),
    )
    task(
        salmon,
        "R03",
        "Взвешивать филе после разделки неделю",
        created_on=day(-16),
        due_on=day(-9),
        status="done",
        done_on=day(-10),
        report="Выход 52% вместо 58% по техкарте",
        outcome_verdict="pending",
        outcome_text="Сколько это дало, посчитаем после ближайшей инвентаризации",
    )
    task(cream, "R05", "Заказывать сливки у поставщика сети", created_on=day(-12), due_on=day(-2))
    session.flush()


TOMATO_TITLE = "Малые партии томатов"
BREAD_TITLE = "Заказ хлеба по дням недели"
# The Sundays the history's checks were launched after (`history_checks`): the history always has them
CHECK_SUNDAYS = (TOMATO_CHECK_FROM - timedelta(days=1), TOMATO_CHECK_FROM + timedelta(days=6))


def check(
    session: Session,
    ctx: AccessContext,
    analyst: UUID,
    finding: Finding,
    *,
    title: str,
    hypothesis: str,
    metric: str,
    test: str,
    controls: list[str],
    starts: date,
    ends: date,
    status: str = "running",
) -> Experiment:
    """A check as the HQ would have proposed and launched it: what it measures fixed at the proposal
    (stage 7), no result — the measurement writes it after the engine's runs."""
    rid = {code: r for r, code in load_facts(session).restaurants.items()}
    spec = design.spec_for(finding, {p.code: p.id for p in session.execute(select(Product)).scalars()})
    before = design.baseline(starts, ends)
    exp = Experiment(
        tenant_id=ctx.tenant_id,
        finding_id=finding.id,
        title=title,
        hypothesis=hypothesis,
        metric=metric,
        baseline=f"{before[0]:%d.%m}–{before[1]:%d.%m}, до проверки",
        test_restaurant_ids=[rid[test]],
        control_restaurant_ids=[rid[c] for c in controls],
        starts_on=starts,
        ends_on=ends,
        expected_rub_month=((finding.effect_rub_month or D(0)) * D("0.6")).quantize(D(1)),
        status=status,
        decided_by=ctx.user_id if status == "running" else None,
        proposed_by=analyst,
        design="restaurants",
        metric_kind=spec.kind if spec else None,
        metric_product_id=spec.product if spec else None,
        metric_cashier=spec.cashier if spec else None,
        baseline_from=before[0],
        baseline_to=before[1],
    )
    session.add(exp)
    session.flush()
    return exp


def history_checks(session: Session, ctx: AccessContext, analyst: UUID, sunday: date) -> None:
    """Checks the HQ launched during the demo's history, on the findings of that week: the later weekly runs
    measure them, so their results come from the data (stage 7), not from this file."""
    by_key = {f.key: f for f in session.execute(select(Finding).where(Finding.key.is_not(None))).scalars()}
    rid = {code: r for r, code in load_facts(session).restaurants.items()}
    plan = {
        CHECK_SUNDAYS[0]: (
            "M5:R04:P06",
            TOMATO_TITLE,
            "Если заказывать томаты через день малыми партиями, списания вернутся к уровню сети.",
            "Списано томатов от закупленного",
            "R04",
            ["R02", "R03"],
            "Перешли на заказ через день, партии по 8 кг",
        ),
        CHECK_SUNDAYS[1]: (
            "M5:R07:P12",
            BREAD_TITLE,
            "Если в понедельник и вторник заказывать на треть меньше хлеба, списания снизятся.",
            "Списано хлеба от закупленного",
            "R07",
            ["R08", "R06"],
            "Меняли заказ на пн и вт, но не каждую неделю",
        ),
    }
    if sunday not in plan:
        return
    key, title, hypothesis, metric, test, controls, report = plan[sunday]
    finding = by_key.get(key)
    if finding is None:
        return
    starts = sunday + timedelta(days=1)
    ends = starts + timedelta(weeks=4) - timedelta(days=1)
    exp = check(
        session,
        ctx,
        analyst,
        finding,
        title=title,
        hypothesis=hypothesis,
        metric=metric,
        test=test,
        controls=controls,
        starts=starts,
        ends=ends,
    )
    finding.status = "in_experiment"
    t = Task(
        tenant_id=ctx.tenant_id,
        restaurant_id=rid[test],
        finding_id=finding.id,
        experiment_id=exp.id,
        title=title,
        assigned_by="hq",
        created_on=starts,
        due_on=ends,
        status="done",
        done_on=ends - timedelta(days=1),
        report=report,
    )
    t.checklist_done = []
    session.add(t)
    session.flush()


def confirm_pending(session: Session, analyst: UUID, today: date) -> None:
    """What an analyst confirmed during the demo's history. The salmon price growth and the dish it makes
    expensive are confirmed too: the prototype's totals are recorded, so a finding confirmed while showing it
    would not reach «Сеть». Today's findings (the pasta shortage, a missing upload) wait in
    «Проверка находок»."""
    for f in session.execute(select(Finding).where(Finding.review_status == ReviewStatus.PENDING)).scalars():
        f.review_status, f.reviewed_by, f.reviewed_on = ReviewStatus.CONFIRMED, analyst, today
    session.flush()


def build(session: Session, ctx: AccessContext, analyst: UUID, today: date, weeks: int) -> RunResult:
    """After the data is loaded: hand-made findings, `weeks` weekly engine runs on the data known by then
    (an analyst confirms what each found), the work on the findings, and today's run."""
    sundays = [last_full_week_end(today) - timedelta(weeks=w) for w in range(weeks, 0, -1)]
    # the weeks the history's checks were launched in, whatever `weeks` (stage 7: they are measured later)
    sundays = sorted(set(sundays) | {s for s in CHECK_SUNDAYS if s < today})
    for sunday in sundays:
        engine.run(session, ctx, sunday + timedelta(days=1), as_of=sunday)
        confirm_pending(session, analyst, sunday + timedelta(days=1))
        history_checks(session, ctx, analyst, sunday)
    work(session, ctx, today, analyst)
    result = engine.run(session, ctx, today)
    # Today's run followed the morning's uploads: the screens say when the findings were updated.
    morning = datetime(today.year, today.month, today.day, 6, 30, tzinfo=UTC)
    session.add(
        AnalyticsRun(
            tenant_id=ctx.tenant_id,
            trigger="upload",
            status=RunStatus.DONE,
            requested_at=morning,
            started_at=morning,
            finished_at=morning + timedelta(minutes=1),
            created=result.created,
            updated=result.updated,
            removed=result.removed,
        )
    )
    # The weeks since the first measured result, now that the work is in place.
    for sunday in sundays[-2:]:
        trend.record_week(session, ctx.tenant_id, sunday + timedelta(days=1))
    return result
