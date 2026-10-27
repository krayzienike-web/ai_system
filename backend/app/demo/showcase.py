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
from app.core.period import last_full_week_end
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
    cream, greens, bread = by_key["M3:R05:P04"], by_key["M5:R01:P10"], by_key["M5:R07:P12"]

    # Mozzarella: a running check with a task in R01 and an interim measurement.
    running = Experiment(
        tenant_id=tid,
        finding_id=moz.id,
        title="Контрольное взвешивание сыра",
        hypothesis="Если две недели взвешивать моцареллу на раздаче, перерасход снизится с 11% до 4%.",
        metric="Расход моцареллы сверх техкарты, %",
        baseline="период 04.08–01.10",
        test_restaurant_ids=[rid["R01"]],
        control_restaurant_ids=[rid["R04"], rid["R05"]],
        starts_on=day(-10),
        ends_on=day(18),
        expected_rub_month=(moz.effect_rub_month or D(0)) * D("0.6"),
        status="running",
        decided_by=ctx.user_id,
        proposed_by=analyst,
        progress_text="Первая неделя: расход сыра по закупкам снизился, точный замер — на пересчете.",
    )
    # Beef: proposed by the analyst, waits for the admin.
    proposed = Experiment(
        tenant_id=tid,
        finding_id=beef.id,
        title="Плановый заказ говядины",
        hypothesis="Если заказывать говядину заранее у основного поставщика, цена вернется к цене сети.",
        metric="Цена говядины, ₽/кг",
        baseline="последние 4 недели",
        test_restaurant_ids=[rid["R02"]],
        control_restaurant_ids=[rid["R03"], rid["R06"]],
        starts_on=day(4),
        ends_on=day(32),
        expected_rub_month=(beef.effect_rub_month or D(0)) * D("0.6"),
        proposed_by=analyst,
    )
    # Rocket: a completed check that worked, ready to roll out.
    greens_effect = ((greens.effect_rub_month or D(0)) * D("0.55")).quantize(D(1))
    done_check = Experiment(
        tenant_id=tid,
        finding_id=greens.id,
        title="Малые партии рукколы",
        hypothesis="Если заказывать рукколу через день малыми партиями, списания снизятся вдвое.",
        metric="Списано рукколы от закупленного, %",
        baseline="4 недели до проверки",
        test_restaurant_ids=[rid["R01"]],
        control_restaurant_ids=[rid["R02"], rid["R03"]],
        starts_on=day(-40),
        ends_on=day(-12),
        expected_rub_month=(greens.effect_rub_month or D(0)) * D("0.6"),
        status="completed",
        verdict="confirmed",
        effect_rub_month=greens_effect,
        ci_low_rub_month=(greens_effect * D("0.6")).quantize(D(1)),
        ci_high_rub_month=(greens_effect * D("1.4")).quantize(D(1)),
        result_text="Списания рукколы в R01 снизились на 55% к периоду до проверки, в ресторанах сравнения — "
        "без "
        "изменений (разница разниц)",
        completed_on=day(-12),
        rollout_rub_month=(greens_effect * 3).quantize(D(1)),
        decided_by=ctx.user_id,
        proposed_by=analyst,
    )
    # Bread: a completed check without a clear effect.
    unclear = Experiment(
        tenant_id=tid,
        finding_id=bread.id,
        title="Заказ хлеба по дням недели",
        hypothesis="Если в понедельник и вторник заказывать на треть меньше хлеба, списания снизятся.",
        metric="Списания хлеба, ₽",
        baseline="4 недели до проверки",
        test_restaurant_ids=[rid["R07"]],
        control_restaurant_ids=[rid["R08"]],
        starts_on=day(-35),
        ends_on=day(-7),
        expected_rub_month=(bread.effect_rub_month or D(0)) * D("0.6"),
        status="completed",
        verdict="inconclusive",
        effect_rub_month=D(0),
        ci_low_rub_month=D(-800),
        ci_high_rub_month=D(1500),
        result_text="Заказ меняли только в половине недель — разница с рестораном сравнения в пределах "
        "колебаний",
        completed_on=day(-7),
        decided_by=ctx.user_id,
        proposed_by=analyst,
    )
    session.add_all([running, proposed, done_check, unclear])
    session.flush()
    for f, status in ((moz, "in_experiment"), (greens, "resolved"), (salmon, "in_work"), (cream, "in_work")):
        f.status = status
    greens.resolved_on = day(-12)

    task(
        moz,
        "R01",
        running.title,
        experiment_id=running.id,
        created_on=day(-10),
        due_on=day(18),
        status="in_progress",
        checklist=["Весы на станции пиццы", "Пересчет моцареллы каждый понедельник"],
    )
    task(
        greens,
        "R01",
        done_check.title,
        experiment_id=done_check.id,
        created_on=day(-40),
        due_on=day(-12),
        status="done",
        done_on=day(-13),
        report="Перешли на заказ через день, партии по 1,5 кг",
        outcome_verdict="confirmed",
        outcome_effect_rub_month=greens_effect,
        outcome_text="Посчитано по итогам проверки: списания рукколы −55%",
        outcome_measured_on=day(-12),
    )
    task(
        bread,
        "R07",
        unclear.title,
        experiment_id=unclear.id,
        created_on=day(-35),
        due_on=day(-7),
        status="done",
        done_on=day(-8),
        report="Меняли заказ на пн и вт, но не каждую неделю",
        outcome_verdict="not_confirmed",
        outcome_text="Эффекта не видно: заказ меняли непостоянно",
        outcome_measured_on=day(-7),
    )
    task(
        salmon,
        "R03",
        "Проверить выход филе при разделке",
        assigned_by="director",
        created_on=day(-9),
        due_on=day(-3),
    )
    task(
        salmon,
        "R03",
        "Взвешивать филе после разделки неделю",
        assigned_by="director",
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


# Left for the prototype's «Проверка находок»: the salmon price growth and what it does to the dish.
LEFT_FOR_REVIEW = {"M3:net:P09:growth", "M2:net:M07"}


def confirm_pending(session: Session, analyst: UUID, today: date) -> None:
    """What an analyst would have confirmed during the demo's history (some findings stay to review)."""
    for f in session.execute(select(Finding).where(Finding.review_status == ReviewStatus.PENDING)).scalars():
        if f.key in LEFT_FOR_REVIEW:
            continue
        f.review_status, f.reviewed_by, f.reviewed_on = ReviewStatus.CONFIRMED, analyst, today
    session.flush()


def build(session: Session, ctx: AccessContext, analyst: UUID, today: date, weeks: int) -> RunResult:
    """After the data is loaded: hand-made findings, `weeks` weekly engine runs on the data known by then
    (an analyst confirms what each found), the work on the findings, and today's run."""
    sundays = [last_full_week_end(today) - timedelta(weeks=w) for w in range(weeks, 0, -1)]
    for sunday in sundays:
        engine.run(session, ctx, sunday + timedelta(days=1), as_of=sunday)
        confirm_pending(session, analyst, sunday + timedelta(days=1))
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
