"""The demo network's work history: what the prototype shows besides the engine's findings (ADR 0007).

- Findings an analyst entered by hand for the planted anomalies of modules that do not exist yet (M4, M5, M7).
  Their figures are computed here from the loaded data, and their keys are the ones the engine will give
  the same problems: when a module arrives, its run takes them over.
- Work on findings: tasks (open, overdue, done with a report), checks (proposed, running, completed with
  a measured result), as HQ and directors would have left them.

Everything is dated relative to `today` (the demo's «today»), so the demo never goes stale.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import engine
from app.analytics.costs import CostBook
from app.analytics.drafts import per_month, rub
from app.analytics.engine import RunResult
from app.analytics.facts import Facts, load_facts
from app.analytics.views import scale_answer
from app.core.period import last_full_week_end
from app.experiments.models import Experiment
from app.insights.models import Finding, ReviewStatus
from app.overview import trend
from app.tasks.models import Task
from app.tenancy.context import AccessContext

D = Decimal


def _r(value: Decimal, places: int = 1) -> float:
    return float(value.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _scale(**kw: Any) -> dict[str, Any]:
    s = {"network": None, "network_label": None, "norm": None, "norm_label": None, **kw}
    s["answer"] = scale_answer(s)
    return s


class _Data:
    """The figures behind the hand-made findings, from the facts known on `today`."""

    def __init__(self, facts: Facts, today: date) -> None:
        self.f = facts
        self.code = {v: k for k, v in facts.restaurants.items()}  # code -> id
        self.product = {p.code: pid for pid, p in facts.products.items()}
        self.costs = CostBook(facts.receipts)
        self.end = max(s.day for s in facts.sales)
        self.start = self.end - timedelta(days=27)

    def write_off_rate(self, product: str) -> dict[str, Decimal]:
        """Written off / bought over the last 4 weeks, per restaurant code."""
        pid = self.product[product]
        bought: dict[UUID, Decimal] = defaultdict(D)
        written: dict[UUID, Decimal] = defaultdict(D)
        for r in self.f.receipts:
            if r.product == pid and self.start <= r.day <= self.end:
                bought[r.restaurant] += r.qty
        for w in self.f.write_offs:
            if w.product == pid and self.start <= w.day <= self.end:
                written[w.restaurant] += w.qty
        return {self.f.restaurants[r]: written[r] / q for r, q in bought.items() if q}

    def write_offs(self, restaurant: str, product: str | None = None) -> list[tuple[date, Decimal]]:
        """Write-offs of a restaurant in rubles, by day, over the last 4 weeks."""
        rid = self.code[restaurant]
        out = []
        for w in self.f.write_offs:
            wanted = product is None or w.product == self.product[product]
            if w.restaurant == rid and self.start <= w.day <= self.end and wanted:
                cost = self.costs.cost(rid, w.product, self.start, self.end)
                if cost is not None:
                    out.append((w.day, w.qty * cost.rub_per_unit))
        return out


def _finding(session: Session, tenant_id: UUID, **kw: Any) -> Finding:
    f = Finding(tenant_id=tenant_id, algorithm_version="manual", review_status=None, **kw)
    session.add(f)
    session.flush()
    return f


def hand_made_findings(session: Session, tenant_id: UUID, facts: Facts, today: date) -> dict[str, Finding]:
    data = _Data(facts, today)
    rid = data.code
    found = today - timedelta(days=12)
    out: dict[str, Finding] = {}

    # M5: rocket in R01 — ordered for 5–6 days with a 3-day shelf life.
    rates = data.write_off_rate("P10")
    others = median([v for k, v in rates.items() if k != "R01"])
    rocket = data.write_offs("R01", "P10")
    wo_rub = sum((v for _, v in rocket), D(0))
    effect = per_month(wo_rub * (1 - others / rates["R01"]), data.start, data.end)
    factor = rates["R01"] / others
    out["greens"] = _finding(
        session,
        tenant_id,
        key="M5:R01:P10",
        module="M5",
        restaurant_id=rid["R01"],
        kind="problem",
        process="writeoffs",
        title="Списания рукколы выше сети",
        headline=(
            f"Рукколу списывают в {_r(factor)} раза чаще, чем в среднем по сети: заказ на 5–6 дней при сроке "
            f"годности 3 дня. Потери ≈ {rub(effect)} в месяц"
        ).replace(".", ",", 1),
        effect_rub_month=effect,
        confidence="high",
        period_from=data.start,
        period_to=data.end,
        found_on=found,
        actions=[
            "Заказывать рукколу через день малыми партиями",
            "Хранить при +2…+4 °C в закрытом контейнере",
        ],
        view={
            "summary": "Руккола портится раньше, чем расходуется: партии больше, чем кухня успевает.",
            "causes": [
                "Заказ на 5–6 дней при сроке годности 3 дня",
                "Нет правила «первым пришел — первым ушел»",
            ],
            "confidence_note": "Акты списания и закупки за 4 недели по всем ресторанам; заведено аналитиком",
            "metric": {
                "label": "Списано от закупленного",
                "value": f"{_r(rates['R01'] * 100)}%",
                "benchmark": f"сеть {_r(others * 100)}%",
            },
            "scale": _scale(
                label="Списано от закупленного",
                unit="%",
                me=_r(rates["R01"] * 100),
                network=_r(others * 100),
                lower_is_better=True,
            ),
        },
    )

    # M4: write-offs right before stock counts in R01 — shortages are closed with write-offs.
    counts = sorted({c.day for c in facts.counts if c.restaurant == rid["R01"]})
    since = counts[0]
    all_wo = [
        (w.day, w.qty * cost.rub_per_unit)
        for w in facts.write_offs
        if w.restaurant == rid["R01"]
        and since < w.day <= data.end
        and (cost := data.costs.cost(rid["R01"], w.product, since, data.end)) is not None
    ]
    total = sum((v for _, v in all_wo), D(0))
    before = sum((v for d, v in all_wo if any(1 <= (c - d).days <= 2 for c in counts)), D(0))
    share = before / total if total else D(0)
    # With write-offs spread evenly, 2 days before each count would hold 2 days' share of them.
    expected = D(2 * (len(counts) - 1)) / (data.end - since).days
    out["pre_count"] = _finding(
        session,
        tenant_id,
        key="M4:R01:pre-count",
        module="M4",
        restaurant_id=rid["R01"],
        kind="problem",
        process="inventory",
        title=f"{_r(share * 100, 0):.0f}% списаний оформлено за 2 дня до инвентаризации",
        headline=(
            f"{_r(share * 100, 0):.0f}% списаний с {since:%d.%m} оформлено за 1–2 дня до пересчета. "
            "Так обычно закрывают недостачи, и реальные потери не видны"
        ),
        effect_rub_month=None,
        effect_note="искажает потери ресторана",
        confidence="medium",
        period_from=since + timedelta(days=1),
        period_to=data.end,
        found_on=found,
        actions=["Оформлять списания в день, когда продукт испорчен", "Выборочно сверить акты с фото"],
        view={
            "summary": "Списания собираются перед инвентаризацией — их используют, чтобы закрыть недостачу.",
            "causes": ["Недостача закрывается актом списания", "Списания не оформляются в момент порчи"],
            "confidence_note": "Даты актов списания и пересчетов с первого пересчета; заведено аналитиком",
            "metric": {
                "label": "Списано за 2 дня до пересчета",
                "value": f"{_r(share * 100, 0):.0f}%",
                "benchmark": f"ровно по дням ≈ {_r(expected * 100, 0):.0f}%",
            },
            "scale": _scale(
                label="Доля списаний за 2 дня до пересчета",
                unit="%",
                me=_r(share * 100, 0),
                norm=_r(expected * 100, 0),
                norm_label="ровно по дням",
                lower_is_better=True,
            ),
        },
    )

    # M5: bread in R07 — the same order every day, Monday and Tuesday sell less.
    bread = data.write_offs("R07", "P12")
    bread_total = sum((v for _, v in bread), D(0))
    early = sum((v for d, v in bread if d.weekday() in (0, 1)), D(0))
    excess = early - bread_total * 2 / 7
    bread_effect = per_month(max(excess, D(0)), data.start, data.end)
    out["bread"] = _finding(
        session,
        tenant_id,
        key="M5:R07:P12",
        module="M5",
        restaurant_id=rid["R07"],
        kind="problem",
        process="writeoffs",
        title="Списания хлеба в понедельник и вторник",
        headline=(
            f"Хлеб заказывают одинаково на все дни, а {_r(early / bread_total * 100, 0):.0f}% списаний — "
            f"в понедельник и вторник, когда продажи ниже. Потери ≈ {rub(bread_effect)} в месяц"
        ),
        effect_rub_month=bread_effect,
        confidence="medium",
        period_from=data.start,
        period_to=data.end,
        found_on=found,
        actions=["Заказывать хлеб по дням недели под продажи"],
        view={
            "summary": "Заказ хлеба не зависит от дня недели, а продажи — зависят.",
            "causes": ["Одинаковый заказ на все дни"],
            "confidence_note": "Акты списания и продажи за 4 недели; заведено аналитиком",
            "metric": {
                "label": "Списания в пн и вт",
                "value": f"{_r(early / bread_total * 100, 0):.0f}%",
                "benchmark": "ожидаемо ≈ 29% (2 дня из 7)",
            },
        },
    )

    # M7: purchases of R09 not uploaded for the last days.
    last_receipt = max(r.day for r in facts.receipts if r.restaurant == rid["R09"])
    gap = (data.end - last_receipt).days
    out["gap"] = _finding(
        session,
        tenant_id,
        key="M7:R09:receipts",
        module="M7",
        restaurant_id=rid["R09"],
        kind="problem",
        process="accounting",
        title=f"Закупки из 1С:ERP загружены только по {last_receipt:%d.%m}",
        headline=f"Закупок нет за последние {gap} дней — цены и приходы за это время не проверены",
        effect_rub_month=None,
        effect_note="цены за неделю не проверены",
        confidence="high",
        period_from=last_receipt + timedelta(days=1),
        period_to=data.end,
        found_on=today - timedelta(days=2),
        actions=["Загрузить закупки за пропущенные дни"],
        view={
            "summary": "Без закупок система не видит цены и приходы этих дней.",
            "causes": [],
            "confidence_note": "Даты загруженных файлов; заведено аналитиком",
        },
    )

    # M4: parmesan and grana mixed up at R11's last count.
    last = max(c.day for c in facts.counts if c.restaurant == rid["R11"])
    diff = {
        code: sum(
            (
                c.actual - (c.book or c.actual)
                for c in facts.counts
                if c.restaurant == rid["R11"] and c.day == last and c.product == data.product[code]
            ),
            D(0),
        )
        for code in ("P02", "P03")
    }
    out["mis_sort"] = _finding(
        session,
        tenant_id,
        key="M4:R11:P02-P03",
        module="M4",
        restaurant_id=rid["R11"],
        kind="problem",
        process="inventory",
        title="Пересорт: пармезан и грана падано",
        headline=(
            f"На пересчете {last:%d.%m} пармезана {_r(diff['P02'], 2):+} кг к учету, "
            f"а граны {_r(diff['P03'], 2):+} кг: "
            "излишек одного почти равен недостаче другого"
        ),
        effect_rub_month=None,
        effect_note="искажает остатки сыров",
        confidence="medium",
        period_from=last,
        period_to=last,
        found_on=today - timedelta(days=9),
        actions=["Разделить хранение сыров и подписать контейнеры", "Пересчитать сыры заново"],
        view={
            "summary": "Похожие сыры перепутали при пересчете.",
            "causes": ["Сыры хранятся вместе без подписей"],
            "confidence_note": "Учетный и фактический остаток на последнем пересчете; заведено аналитиком",
        },
    )

    # M7: the pumpkin soup sells without a recipe.
    soup = next(m for m, info in facts.menu.items() if info.code == "M12")
    revenue = sum(
        (s.revenue for s in facts.sales if s.menu_item == soup and data.start <= s.day <= data.end), D(0)
    )
    all_revenue = sum((s.revenue for s in facts.sales if data.start <= s.day <= data.end), D(0))
    out["no_recipe"] = _finding(
        session,
        tenant_id,
        key="M7:net:M12",
        module="M7",
        restaurant_id=None,
        kind="problem",
        process="accounting",
        title="«Тыквенный суп» продается без техкарты",
        headline=(
            f"С 01.09 суп продается без техкарты: {_r(revenue / all_revenue * 100)}% выручки сети, расход "
            "продуктов на него система не видит"
        ).replace(".", ",", 1),
        effect_rub_month=None,
        effect_note="фудкост сети считается неточно",
        confidence="high",
        period_from=date(2026, 9, 1),
        period_to=data.end,
        found_on=today - timedelta(days=30),
        actions=["Завести техкарту «Тыквенного супа» в iiko"],
        view={
            "summary": "Блюдо без техкарты: его продукты уходят «в никуда» и попадают в потери.",
            "causes": ["Сезонное блюдо ввели без техкарты"],
            "confidence_note": "Продажи r_keeper и справочник техкарт; заведено аналитиком",
        },
    )
    return out


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
    hand_made_findings(session, ctx.tenant_id, load_facts(session), today)
    sundays = [last_full_week_end(today) - timedelta(weeks=w) for w in range(weeks, 0, -1)]
    for sunday in sundays:
        engine.run(session, ctx, sunday + timedelta(days=1), as_of=sunday)
        confirm_pending(session, analyst, sunday + timedelta(days=1))
    work(session, ctx, today, analyst)
    result = engine.run(session, ctx, today)
    # The weeks since the first measured result, now that the work is in place.
    for sunday in sundays[-2:]:
        trend.record_week(session, ctx.tenant_id, sunday + timedelta(days=1))
    return result
