"""Measures the checks after every engine run (stage 7; docs/05, «Замер»).

The numbers come from `analytics.measure` (difference in differences on the uploaded rows); this module only
decides when to measure and writes what the measurement says:

- a running check whose period has not ended — an interim measurement in `progress_text`, no verdict;
- its period has ended and the rows are uploaded up to its last day — the result (`record_result`): verdict,
  effect and interval in ₽ a month, the text — by rules, every number from the measurement;
- the period has ended, the rows not yet — «ждем данных по DD.MM».
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.drafts import dmy, pct, rub
from app.analytics.facts import Facts
from app.analytics.measure import Result, Spec, Unit, forecast_rub_month, measure
from app.analytics.usage import Usage
from app.experiments import design
from app.experiments.design import baseline, seed
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.experiments.service import record_result
from app.insights.models import Finding
from app.tenancy.context import AccessContext

UNIT = {"kg": "кг", "l": "л", "pcs": "шт"}
log = logging.getLogger(__name__)


def units(exp: Experiment) -> tuple[Unit, list[Unit]]:
    spec = Spec(str(exp.metric_kind), exp.metric_product_id, exp.metric_cashier)
    return design.units(
        spec,
        exp.design,
        exp.test_restaurant_ids[0],
        list(exp.control_restaurant_ids),
        list(exp.control_product_ids),
    )


def _last_days(facts: Facts, spec: Spec, restaurants: set[UUID]) -> dict[UUID, date | None]:
    """Each restaurant's last day with the rows the metric needs (sales, and for a product also receipts)."""
    sales: dict[UUID, date] = {}
    for s in facts.sales:
        if s.restaurant in restaurants:
            sales[s.restaurant] = max(sales.get(s.restaurant, s.day), s.day)
    if spec.kind in ("discounts", "voids"):
        return {r: sales.get(r) for r in restaurants}
    bought: dict[UUID, date] = {}
    for x in facts.receipts:
        if x.restaurant in restaurants:
            bought[x.restaurant] = max(bought.get(x.restaurant, x.day), x.day)
    return {r: min(sales[r], bought[r]) if r in sales and r in bought else None for r in restaurants}


GRACE_DAYS = 14  # after the end, a control restaurant without its rows waits this long, then is left out


def describe(spec: Spec, facts: Facts) -> tuple[str, str]:
    """(the metric in words, the kind of number): («списано от закупленного — «Томаты»», "share")."""
    info = facts.products.get(spec.product) if spec.product else None
    name = f" — «{info.name}»" if info else ""
    who = f" — кассир {spec.cashier}" if spec.cashier else ""
    if spec.kind == "overuse":
        return f"закуплено к расходу по техкартам{name}", "share"
    if spec.kind == "writeoffs":
        return f"списано к расходу по техкартам{name}", "share"
    if spec.kind == "price":
        unit = UNIT.get(info.unit, info.unit) if info else "ед."
        return f"цена закупки, ₽/{unit}{name}", "price"
    if spec.kind == "discounts":
        return f"скидки от продаж до скидок{who}", "share"
    return f"удалено после пречека, ₽ в день{who}", "rub"


def _num(value: Decimal, how: str) -> str:
    if how == "share":
        return pct(value)
    if how == "price":  # a price moves by kopecks: «212,40 ₽» (code review of stage 7, p. 15)
        return f"{value.quantize(Decimal('0.01')):,.2f}".replace(",", "\u00a0").replace(".", ",") + "\u00a0₽"
    return rub(value)


def _signed(value: Decimal) -> str:
    """A sum with its sign, as people write it: «−1 104 ₽», «+785 ₽», «0 ₽»."""
    text = rub(abs(value))
    return f"−{text}" if value < 0 else f"+{text}" if value > 0 else text


def text(
    spec: Spec, facts: Facts, r: Result, where: str, *, interval: bool = True, capital: bool = True
) -> str:
    """The measurement in words — every number from `r` (docs/05: the numbers come from the measurement)."""
    metric, how = describe(spec, facts)
    head = metric[0].upper() + metric[1:] if capital else metric
    out = f"{head}, {where}: {_num(r.test_before, how)} → {_num(r.test_after, how)}"
    if r.control_before is not None and r.control_after is not None:
        control = "другие товары категории" if r.design == "items" else "рестораны сравнения"
        out += f"; {control}: {_num(r.control_before, how)} → {_num(r.control_after, how)}"
    sign = "−" if r.effect < 0 else "+" if r.effect > 0 else ""
    change = f"{pct(abs(r.effect))[:-1]} п.п." if how == "share" else _num(abs(r.effect), how)
    kind = "Разница разниц" if r.control_before is not None else "Изменение"
    out += f". {kind} {sign}{change} — {_signed(r.effect_rub_month)} в месяц"
    if interval:
        out += f" (95%: {_signed(r.ci_low_rub_month)} … {_signed(r.ci_high_rub_month)})"
    if r.weak:
        out += ". Сравнить не с чем — слабое доказательство"
    for note in r.notes:
        out += f". {note[0].upper() + note[1:]}"
    return out


EARLY_DAYS = 14  # an interim measurement over fewer days shows the direction, not an interval


def measure_all(
    session: Session, ctx: AccessContext, facts: Facts, today: date, usage: Usage | None = None
) -> int:
    """Measures the network's running checks on `facts`; returns how many got a result."""
    running = list(
        session.execute(
            select(Experiment).where(
                Experiment.tenant_id == ctx.tenant_id, Experiment.status == ExperimentStatus.RUNNING
            )
        ).scalars()
    )
    if not running:
        return 0
    usage = usage or Usage(facts)
    finished = 0
    for exp in running:
        if exp.metric_kind is None and not _backfill(session, exp, facts, today):
            continue
        try:
            finished += _measure_one(session, exp, facts, usage, today)
        except (ValueError, ArithmeticError):  # one broken check never stops the network's run (p. 14)
            log.exception("Check %s could not be measured", exp.id)
            exp.progress_text = "Замер не удался — проверьте товар и рестораны проверки."
    session.flush()
    return finished


def _backfill(session: Session, exp: Experiment, facts: Facts, today: date) -> bool:
    """A check launched before the measurement existed (stages 4–6): its metric from its finding; no metric —
    it was never going to be measured, and after its end it is closed by its tasks (code review 7, p. 3)."""
    finding = session.get(Finding, exp.finding_id) if exp.finding_id else None
    codes = {info.code: p for p, info in facts.products.items()}
    spec = design.spec_for(finding, codes) if finding else None
    if spec is not None:
        exp.metric_kind, exp.metric_product_id, exp.metric_cashier = spec.kind, spec.product, spec.cashier
        exp.baseline_from, exp.baseline_to = design.baseline(exp.starts_on, exp.ends_on)
        return True
    if today > exp.ends_on:
        record_result(
            session,
            exp,
            verdict=Verdict.INCONCLUSIVE,
            effect_rub_month=Decimal(0),
            ci_low=Decimal(0),
            ci_high=Decimal(0),
            text="Эту меру замер не считает: итог — по задачам ресторанов",
            completed_on=today,
        )
    return False


def _measure_one(session: Session, exp: Experiment, facts: Facts, usage: Usage, today: date) -> int:
    spec = Spec(str(exp.metric_kind), exp.metric_product_id, exp.metric_cashier)
    test, controls = units(exp)
    last_days = _last_days(facts, spec, {test.restaurant, *(u.restaurant for u in controls)})
    # a control restaurant that stopped uploading is left out after a grace period (code review 7, p. 9)
    late = [
        u
        for u in controls
        if u.restaurant != test.restaurant and (last_days.get(u.restaurant) or date.min) < exp.ends_on
    ]
    dropped: list[str] = []
    if late and today > exp.ends_on + timedelta(days=GRACE_DAYS):
        if len(late) == len(controls):  # nobody left to compare with: close it, never wait for ever
            names = ", ".join(facts.restaurants.get(u.restaurant, "?") for u in late)
            record_result(
                session,
                exp,
                verdict=Verdict.INCONCLUSIVE,
                effect_rub_month=Decimal(0),
                ci_low=Decimal(0),
                ci_high=Decimal(0),
                text=f"Сравнить не с чем: рестораны сравнения ({names}) не загрузили данные за период",
                completed_on=today,
            )
            exp.measured_on, exp.progress_text = today, None
            return 1
        controls = [u for u in controls if u not in late]
        dropped = [facts.restaurants.get(u.restaurant, "?") for u in late]
    ends = [last_days.get(test.restaurant)] + [last_days.get(u.restaurant) for u in controls]
    end = min(ends) if all(ends) else None  # type: ignore[type-var]
    before = (
        (exp.baseline_from, exp.baseline_to)
        if exp.baseline_from and exp.baseline_to
        else baseline(exp.starts_on, exp.ends_on)
    )
    exp.measured_on = today
    if end is None or end < exp.starts_on:
        exp.progress_text = "Данных после начала проверки пока нет — замер после загрузки продаж и закупок."
        return 0
    last = min(end, exp.ends_on)
    r = measure(facts, usage, spec, exp.design, test, controls, before, (exp.starts_on, last), seed(exp.id))
    where = facts.restaurants.get(test.restaurant, "ресторане")
    if r is None:
        if end >= exp.ends_on:  # the period is over and there is nothing to compare: say so and close
            record_result(
                session,
                exp,
                verdict=Verdict.INCONCLUSIVE,
                effect_rub_month=Decimal(0),
                ci_low=Decimal(0),
                ci_high=Decimal(0),
                text="Замерить нечего: за период проверки или до нее нет строк по этому показателю",
                completed_on=today,
            )
            exp.progress_text = None
            return 1
        exp.progress_text = "По этому показателю пока нет строк за период проверки."
        return 0
    if dropped:
        r.notes.append("без " + ", ".join(dropped) + " — их данных за период нет")
    if end >= exp.ends_on:
        record_result(
            session,
            exp,
            verdict=Verdict(r.verdict),
            effect_rub_month=r.effect_rub_month,
            ci_low=r.ci_low_rub_month,
            ci_high=r.ci_high_rub_month,
            text=text(spec, facts, r, where),
            completed_on=today,
        )
        exp.progress_text = None
        if r.verdict == "confirmed":
            # rolling it out: the other restaurants, over the check's own weeks (docs/05, step 7)
            others = [p for p in facts.restaurants if p not in exp.test_restaurant_ids]
            exp.rollout_rub_month = forecast_rub_month(facts, usage, spec, r, others, (exp.starts_on, last))
        return 1
    if today > exp.ends_on:
        exp.progress_text = f"Срок прошел; ждем данных по {dmy(exp.ends_on)}, чтобы подвести итог."
    else:
        early = r.days_after < EARLY_DAYS
        words = text(spec, facts, r, where, interval=not early, capital=False)
        exp.progress_text = (
            f"За {r.days_after} дн. проверки: {words}. "
            + ("Судить рано — " if early else "")
            + f"итог после {dmy(exp.ends_on)}."
        )
    return 0
