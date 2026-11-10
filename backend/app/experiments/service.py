"""Checks: HQ launches or rejects a proposal; launching sets tasks for the test restaurants."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.facts import load_facts
from app.analytics.measure import Spec, mde_by_weeks
from app.analytics.usage import Usage
from app.catalog.models import Product
from app.core import words
from app.core.errors import ForbiddenError, InvalidError, NotFoundError
from app.experiments import design
from app.experiments.models import Experiment, ExperimentStatus, Verdict
from app.insights.models import Finding, FindingStatus
from app.overview.models import KpiSnapshot
from app.tasks.models import AssignedBy, OutcomeVerdict, Task, TaskStatus
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant
from app.tenancy.permissions import Permission


def _proposal(session: Session, ctx: AccessContext, experiment_id: UUID) -> Experiment:
    if not ctx.can(Permission.EXPERIMENTS_LAUNCH):
        raise ForbiddenError("Only HQ admins launch checks")
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise NotFoundError("Check not found")
    if exp.status != ExperimentStatus.PROPOSED:
        raise InvalidError("The check is not waiting for a decision")
    return exp


def launch(session: Session, ctx: AccessContext, experiment_id: UUID, *, today: date) -> list[Task]:
    exp = _proposal(session, ctx, experiment_id)
    if exp.finding_id is not None:
        finding = session.get(Finding, exp.finding_id)
        if finding is not None and not finding.checked:
            raise InvalidError(
                "Находка еще не прошла проверку: проверку изменений запускают после подтверждения"
            )
    if exp.ends_on <= today:
        raise InvalidError("The check would end before it starts; change its dates")
    exp.status = ExperimentStatus.RUNNING
    if exp.starts_on < today:
        # Launched late: the whole period moves, its length and the weeks before it with it — the measurement
        # compares what was approved (code review of stage 7, p. 6; docs/05 «Периоды»)
        length = exp.ends_on - exp.starts_on
        exp.starts_on, exp.ends_on = today, today + length
        if exp.baseline_from is not None:
            exp.baseline_from, exp.baseline_to = design.baseline(exp.starts_on, exp.ends_on)
            exp.baseline = f"{exp.baseline_from:%d.%m}–{exp.baseline_to:%d.%m}, до проверки"
    exp.decided_by = ctx.user_id
    exp.decided_at = datetime.now(UTC)
    tasks = [
        Task(
            tenant_id=ctx.tenant_id,
            restaurant_id=rid,
            finding_id=exp.finding_id,
            experiment_id=exp.id,
            title=exp.title,
            assigned_by=AssignedBy.HQ,
            created_by=ctx.user_id,
            created_on=today,
            due_on=exp.ends_on,
            status=TaskStatus.ASSIGNED,
        )
        for rid in exp.test_restaurant_ids
    ]
    session.add_all(tasks)
    if exp.finding_id is not None:
        finding = session.get(Finding, exp.finding_id)
        if finding is not None and finding.status in (FindingStatus.NEW, FindingStatus.IN_WORK):
            finding.status = FindingStatus.IN_EXPERIMENT
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.launch",
        entity="experiment",
        entity_id=exp.id,
    )
    return tasks


def reject(session: Session, ctx: AccessContext, experiment_id: UUID) -> Experiment:
    exp = _proposal(session, ctx, experiment_id)
    exp.status = ExperimentStatus.REJECTED
    exp.decided_by = ctx.user_id
    exp.decided_at = datetime.now(UTC)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.reject",
        entity="experiment",
        entity_id=exp.id,
    )
    return exp


# How long a check runs: the choice offered to HQ, with what it means.
DURATIONS = [
    (2, "быстро, но вывод будет менее надежным"),
    (4, "оптимально: две-три недели продаж и пересчет"),
    (6, "надежнее, если продажи сильно скачут"),
]
DEFAULT_WEEKS = 4
MAX_WEEKS = 12  # a repeated check may run longer than the usual choices
EXPECTED_SHARE = Decimal("0.6")  # a check is expected to return 60 % of the finding: a cautious estimate
CONTROL_SIZE = 3  # restaurants to compare with, the most similar by revenue
START_IN_DAYS = 3  # the director gets a few days to prepare


@dataclass(frozen=True)
class Candidate:
    restaurant_id: UUID
    code: str
    name: str
    suggested: bool
    reason: str


@dataclass(frozen=True)
class Draft:
    finding: Finding
    actions: list[str]
    test: Restaurant
    candidates: list[Candidate]
    durations: list[tuple[int, str]]
    default_weeks: int
    expected_rub_month: Decimal
    metric: str  # what is measured, as the finding names it
    target: str  # where it should move: «уровню сети» or «норме»
    success: str
    # stage 7 (docs/05): what the measurement measures, the designs that fit, the one the system suggests
    spec: Spec | None = None
    designs: list[design.Option] = field(default_factory=list)
    recommended: str = "restaurants"
    hypothesis: str = ""


def _proposable(session: Session, ctx: AccessContext, finding_id: UUID) -> Finding:
    if not ctx.can(Permission.EXPERIMENTS_PROPOSE):
        raise ForbiddenError("Проверки готовит управляющая компания")
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("Finding not found")
    if not finding.checked:
        raise InvalidError("Находка еще не прошла проверку")
    if finding.restaurant_id is None:
        raise InvalidError("Проверку ставят на одном ресторане: у сетевой находки ее нет")
    return finding


def draft(session: Session, ctx: AccessContext, finding_id: UUID, *, designs: bool = True) -> Draft:
    """The check the system proposes for a finding: what to change, where, compared with whom, how long
    (`designs=False` — without the designs and their thresholds: `propose` works them out for its own
    choice, so the rows are not read and measured twice)."""
    finding = _proposable(session, ctx, finding_id)
    places = {r.id: r for r in session.execute(select(Restaurant)).scalars()}
    revenue = {
        k.restaurant_id: k.revenue
        for k in session.execute(select(KpiSnapshot).where(KpiSnapshot.restaurant_id.is_not(None))).scalars()
    }
    test = places[finding.restaurant_id]  # type: ignore[index]
    mine = revenue.get(test.id)
    others = [r for r in places.values() if r.id != test.id]

    def distance(r: Restaurant) -> Decimal:
        if not mine or r.id not in revenue:  # no revenue yet (no stock-count period): no comparison
            return Decimal(10**9)
        return abs(revenue[r.id] - mine) / mine

    others.sort(key=lambda r: (distance(r), r.code))
    candidates = [
        Candidate(
            r.id,
            r.code,
            r.name,
            i < CONTROL_SIZE,
            f"выручка отличается на {round(distance(r) * 100)}%"
            if r.id in revenue and mine
            else "нет данных о выручке",
        )
        for i, r in enumerate(others)
    ]
    view = finding.view or {}
    label = (view.get("scale") or {}).get("label") or (view.get("metric") or {}).get("label") or "Показатель"
    target = "уровню сети" if (view.get("scale") or {}).get("network") is not None else "норме"
    expected = ((finding.effect_rub_month or Decimal(0)) * EXPECTED_SHARE / 100).quantize(Decimal(1)) * 100
    weeks = DEFAULT_WEEKS
    codes = {p.code: p.id for p in session.execute(select(Product)).scalars()}
    spec = design.spec_for(finding, codes)
    options: list[design.Option] = []
    suggest = "restaurants"
    if spec is not None and designs:
        facts = load_facts(session)
        last = max((r.day for r in facts.receipts), default=None)
        if last is not None:
            starts = last + timedelta(days=1)
            controls = [c.restaurant_id for c in candidates if c.suggested]
            options = design.options(
                facts,
                spec,
                test.id,
                controls,
                starts,
                starts + timedelta(weeks=weeks),
                finding.id.int % 2**32,
            )
            suggest = design.recommended(options, expected, weeks)
    return Draft(
        finding=finding,
        actions=list(finding.actions),
        test=test,
        candidates=candidates,
        durations=DURATIONS,
        default_weeks=weeks,
        expected_rub_month=expected,
        metric=label,
        target=target,
        success=(
            f"«{label}» приблизится к {target}. Ожидаем +{words.per_month(expected)} — "
            f"{round(EXPECTED_SHARE * 100)}% от найденного, оценка с запасом."
        ),
        spec=spec,
        designs=options,
        recommended=suggest,
        # the template of docs/05, step 2: {action} and {weeks} are what the HQ picks in the wizard
        hypothesis=(
            f"Если в ресторане «{test.name}» {{action}}, «{label}» приблизится к {target} за {{weeks}}"
            + (f" — это +{words.per_month(expected)}." if expected > 0 else ".")
        ),
    )


def hypothesis(template: str, action: str, weeks: int) -> str:
    """The hypothesis of a check by the template of docs/05, step 2: the measure and the length filled in."""
    return template.replace("{action}", action[0].lower() + action[1:]).replace(
        "{weeks}", words.plural(weeks, ("неделю", "недели", "недель"))
    )


def propose(
    session: Session,
    ctx: AccessContext,
    finding_id: UUID,
    *,
    action: str,
    control_ids: list[UUID],
    weeks: int,
    today: date,
    design_key: str = "restaurants",
    repeat_of: Experiment | None = None,
) -> Experiment:
    """A check of a finding, sent to the HQ admin to launch. Its design, metric and periods are fixed here
    and never change after the launch (docs/05, «Честность замера»)."""
    d = draft(session, ctx, finding_id, designs=False)
    session.refresh(d.finding, with_for_update=True)  # two proposals at once: one waits for the other
    open_check = session.execute(
        select(Experiment.id).where(
            Experiment.finding_id == d.finding.id,
            Experiment.status.in_((ExperimentStatus.PROPOSED, ExperimentStatus.RUNNING)),
        )
    ).first()
    if open_check:
        raise InvalidError("По этой находке уже есть проверка")
    if action not in d.actions and (repeat_of is None or action != repeat_of.title):
        raise InvalidError("Выберите меру из находки")
    if weeks not in {w for w, _ in DURATIONS} and not (repeat_of is not None and weeks <= MAX_WEEKS):
        raise InvalidError("Недопустимая длительность проверки")
    allowed = {c.restaurant_id for c in d.candidates}
    if not set(control_ids) <= allowed:
        raise InvalidError("Сравнивать можно только с другими ресторанами сети")
    if design_key not in design.DESIGNS:
        raise InvalidError("Неизвестный дизайн проверки")
    if d.spec is None:
        # docs/05: a finding the measurement does not measure goes as a task (code review of stage 7, p. 3)
        raise InvalidError("Эту находку замер не считает — поставьте задачу директору")
    if design_key == "restaurants" and not control_ids:
        raise InvalidError("Выберите рестораны для сравнения")
    starts = today + timedelta(days=START_IN_DAYS)
    ends = starts + timedelta(weeks=weeks)
    before = design.baseline(starts, ends)
    # The design as proposed: its availability and the smallest effect for these restaurants, this length
    # and these dates, not the draft's defaults (code review of stage 7, p. 7)
    facts = load_facts(session)
    usage = Usage(facts)
    chosen = next(
        (
            o
            for o in design.options(
                facts, d.spec, d.test.id, control_ids, starts, ends, d.finding.id.int % 2**32, usage
            )
            if o.design == design_key
        ),
        None,
    )
    if chosen is None or not chosen.available:
        raise InvalidError("Этот дизайн для находки не подходит")
    mde = (
        mde_by_weeks(
            facts,
            usage,
            d.spec,
            design_key,
            *design.units(d.spec, design_key, d.test.id, control_ids, chosen.control_products),
            before,
            d.finding.id.int % 2**32,
            [weeks],
        )
        if weeks not in design.WEEKS
        else None
    )
    exp = Experiment(
        tenant_id=ctx.tenant_id,
        finding_id=d.finding.id,
        title=action,
        hypothesis=hypothesis(d.hypothesis, action, weeks),
        metric=d.metric,
        baseline=f"{before[0]:%d.%m}–{before[1]:%d.%m}, до проверки",
        test_restaurant_ids=[d.test.id],
        control_restaurant_ids=control_ids if design_key == "restaurants" else [],
        starts_on=starts,
        ends_on=ends,
        expected_rub_month=d.expected_rub_month,
        proposed_by=ctx.user_id,
        design=design_key,
        metric_kind=d.spec.kind,
        metric_product_id=d.spec.product,
        metric_cashier=d.spec.cashier,
        control_product_ids=chosen.control_products if design_key == "items" else [],
        baseline_from=before[0],
        baseline_to=before[1],
        mde_rub_month=(mde or {}).get(weeks) if mde else chosen.mde(weeks),
    )
    session.add(exp)
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.propose",
        entity="experiment",
        entity_id=exp.id,
    )
    return exp


def repeat(
    session: Session, ctx: AccessContext, experiment_id: UUID, *, weeks: int, today: date
) -> Experiment:
    """A result that is not significant: the same check again, longer — a new check with its own periods
    (a running check's period never changes after the launch, docs/05 «Честность замера»)."""
    if not ctx.can(Permission.EXPERIMENTS_PROPOSE):
        raise ForbiddenError("Проверки готовит управляющая компания")
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise NotFoundError("Check not found")
    if exp.status != ExperimentStatus.COMPLETED or exp.verdict == Verdict.CONFIRMED:
        raise InvalidError("Повторяют проверку, которая не подтвердила эффект")
    if exp.finding_id is None:
        raise InvalidError("У проверки нет находки")
    if weeks <= round((exp.ends_on - exp.starts_on).days / 7):
        raise InvalidError("Повторная проверка — дольше прежней")
    if weeks > MAX_WEEKS:
        raise InvalidError(f"Проверка — не дольше {MAX_WEEKS} недель")
    return propose(
        session,
        ctx,
        exp.finding_id,
        action=exp.title,
        control_ids=list(exp.control_restaurant_ids),
        weeks=weeks,
        today=today,
        design_key=exp.design,
        repeat_of=exp,
    )


def rollout(session: Session, ctx: AccessContext, experiment_id: UUID, *, today: date) -> list[Task]:
    """A change that worked goes to every restaurant that has not done it yet: one task each."""
    if not ctx.can(Permission.EXPERIMENTS_LAUNCH):
        raise ForbiddenError("Only HQ admins roll changes out")
    # Locked: a double click or two requests must not send the tasks twice.
    exp = session.get(Experiment, experiment_id, with_for_update=True, populate_existing=True)
    if exp is None:
        raise NotFoundError("Check not found")
    if exp.verdict != Verdict.CONFIRMED:
        raise InvalidError("Тиражируют только то, что сработало")
    if exp.rollout_on is not None:
        raise InvalidError("Изменение уже отправлено во все рестораны")
    targets = [
        r.id
        for r in session.execute(select(Restaurant).order_by(Restaurant.code)).scalars()
        if r.id not in exp.test_restaurant_ids
    ]
    tasks = [
        Task(
            tenant_id=ctx.tenant_id,
            restaurant_id=rid,
            finding_id=exp.finding_id,
            experiment_id=exp.id,
            title=exp.title,
            assigned_by=AssignedBy.HQ,
            created_by=ctx.user_id,
            created_on=today,
            due_on=today + timedelta(days=14),
            status=TaskStatus.ASSIGNED,
        )
        for rid in targets
    ]
    session.add_all(tasks)
    exp.rollout_on = today
    session.flush()
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="experiment.rollout",
        entity="experiment",
        entity_id=exp.id,
        payload={"restaurants": len(tasks)},
    )
    return tasks


def record_result(
    session: Session,
    exp: Experiment,
    *,
    verdict: Verdict,
    effect_rub_month: Decimal,
    ci_low: Decimal,
    ci_high: Decimal,
    text: str,
    completed_on: date,
) -> None:
    """Called by the measurement (difference in differences) only. The effect stays on the check, so it is
    never counted twice; its done tasks get the verdict as their outcome."""
    if exp.status != ExperimentStatus.RUNNING:
        raise InvalidError("Only a running check gets a result")
    if not ci_low <= effect_rub_month <= ci_high:
        raise InvalidError("The effect must lie inside its interval")
    exp.status = ExperimentStatus.COMPLETED
    exp.verdict = verdict
    exp.effect_rub_month = effect_rub_month
    exp.ci_low_rub_month = ci_low
    exp.ci_high_rub_month = ci_high
    exp.result_text = text
    exp.completed_on = completed_on
    task_verdict = OutcomeVerdict.CONFIRMED if verdict == Verdict.CONFIRMED else OutcomeVerdict.NOT_CONFIRMED
    for task in session.execute(
        select(Task).where(Task.experiment_id == exp.id, Task.status == TaskStatus.DONE)
    ).scalars():
        task.outcome_verdict = task_verdict
        task.outcome_text = text
        task.outcome_measured_on = completed_on
    session.flush()
