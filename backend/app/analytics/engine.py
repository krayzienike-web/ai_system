"""One run of the engine: facts → metrics → detectors → findings (docs/02 «Пересчет», docs/12).

Idempotent: a finding is matched to its draft by `key`. A re-run updates numbers and texts and keeps the
status and the work (tasks, checks). A finding that is no longer detected disappears only if nobody has
started working on it; otherwise it stays as it is for a person to close.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import kpi, m1, m2, m3, params, views
from app.analytics.costs import CostBook
from app.analytics.drafts import Draft
from app.analytics.facts import Facts, load_facts
from app.analytics.params import DEFAULT, EngineParams
from app.analytics.usage import Usage
from app.core.errors import ForbiddenError
from app.experiments.models import Experiment
from app.insights.models import Finding, FindingStatus, ReviewStatus
from app.norms.service import Norms, load_norms
from app.overview import trend
from app.overview.models import KpiSnapshot
from app.tasks.models import Task
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

ALGORITHM_VERSION = "engine-2"  # M1: peers by nearest periods, usage below the recipe
MODULES = ("M1", "M2", "M3")  # modules this version runs; findings of other modules are left alone


@dataclass(frozen=True)
class RunResult:
    created: int
    updated: int
    removed: int
    drafts: int


def analyse(facts: Facts, norms: Norms, cfg: EngineParams = DEFAULT) -> tuple[list[Draft], list[kpi.Kpi]]:
    """Findings of every module and the restaurants' KPIs, from one pass over the facts."""
    usage = Usage(facts)
    costs = CostBook(facts.receipts)
    m1_rows = m1.rows(facts, usage, costs, cfg)
    drafts = (
        m1.detect(facts, m1_rows, norms, cfg)
        + m2.detect(facts, norms, cfg)
        + m3.detect(facts, cfg)
        + m3.detect_contracts(facts, cfg)
        + m3.detect_network_growth(facts, cfg)
    )
    for d in drafts:
        d.view = views.build(d, facts)
    return drafts, kpi.compute(facts, m1_rows, costs)


def detect(facts: Facts, norms: Norms, cfg: EngineParams = DEFAULT) -> list[Draft]:
    return analyse(facts, norms, cfg)[0]


def _changed_much(f: Finding, d: Draft, cfg: EngineParams) -> bool:
    """Whether a checked finding no longer says what the reviewer saw."""
    if f.review_status not in (ReviewStatus.CONFIRMED, ReviewStatus.REJECTED):
        return False
    if f.kind != d.kind or f.restaurant_id != d.restaurant:
        return True
    old, new = f.effect_rub_month, d.effect_rub_month
    if old is None or new is None:
        return (old is None) != (new is None)
    if not old:
        return bool(new)
    return abs(new - old) / abs(old) > cfg.REVIEW_RECHECK_CHANGE


def _store_kpis(session: Session, tenant_id: UUID, kpis: list[kpi.Kpi], today: date) -> None:
    """The snapshot is replaced as a whole: the same data gives the same rows (idempotent)."""
    session.execute(delete(KpiSnapshot))
    session.add_all(
        KpiSnapshot(
            tenant_id=tenant_id,
            restaurant_id=k.restaurant,
            computed_on=today,
            food_cost_from=k.food_cost_from,
            food_cost_to=k.food_cost_to,
            revenue=k.revenue,
            food_cost_actual=k.food_cost_actual,
            food_cost_theory=k.food_cost_theory,
            write_offs_from=k.write_offs_from,
            write_offs_to=k.write_offs_to,
            write_offs_share=k.write_offs_share,
        )
        for k in kpis
    )
    session.flush()


def run(session: Session, ctx: AccessContext, today: date, *, as_of: date | None = None) -> RunResult:
    """Recomputes the findings. `as_of`: only the data up to that day (recomputing the past: the demo)."""
    if not ctx.can(Permission.ANALYTICS_RUN) or not ctx.role.is_hq:
        raise ForbiddenError("Пересчет находок запускает администратор управляющей компании")
    norms = load_norms(session)
    cfg = params.load(session)
    facts = load_facts(session)
    drafts, kpis = analyse(facts.until(as_of) if as_of else facts, norms, cfg)
    keys = [d.key for d in drafts]
    if len(keys) != len(set(keys)):
        raise RuntimeError(
            f"Engine produced duplicate finding keys: {sorted({k for k in keys if keys.count(k) > 1})}"
        )
    existing = {
        f.key: f
        for f in session.execute(select(Finding).where(Finding.key.is_not(None))).scalars()
        if f.key and f.key.split(":", 1)[0] in MODULES
    }
    created = updated = removed = 0
    for d in drafts:
        f = existing.pop(d.key, None)
        if f is None:
            f = Finding(
                tenant_id=ctx.tenant_id,
                key=d.key,
                found_on=today,
                status=FindingStatus.NEW,
                review_status=ReviewStatus.PENDING if norms.review_findings else ReviewStatus.CONFIRMED,
            )
            session.add(f)
            created += 1
        else:
            updated += 1
            if f.review_status is None:
                # Made by hand and already worked on: a person has checked it.
                f.review_status = ReviewStatus.CONFIRMED
            elif norms.review_findings and _changed_much(f, d, cfg):
                # New data changed what was checked: a director must not see an amount nobody confirmed,
                # and a rejected finding that got much bigger deserves another look.
                was = f.effect_rub_month
                f.review_status = ReviewStatus.PENDING
                f.review_reason, f.reviewed_on, f.reviewed_by = None, None, None
                f.review_note = f"Снова на проверке: эффект изменился с {was} до {d.effect_rub_month} ₽/мес"
        f.restaurant_id = d.restaurant
        f.module, f.kind, f.process = d.module, d.kind, d.process
        f.title, f.headline = d.title, d.headline
        f.effect_rub_month, f.effect_note = d.effect_rub_month, d.effect_note
        f.confidence, f.period_from, f.period_to = d.confidence, d.period_from, d.period_to
        f.actions, f.evidence, f.view = d.actions, d.evidence, d.view
        f.algorithm_version = ALGORITHM_VERSION
    stale = [f.id for f in existing.values()]
    worked_on = set(session.execute(select(Task.finding_id).where(Task.finding_id.in_(stale))).scalars())
    worked_on |= set(
        session.execute(select(Experiment.finding_id).where(Experiment.finding_id.in_(stale))).scalars()
    )
    for f in existing.values():
        # A rejected finding stays as the record of the reviewer's decision.
        if (
            f.status == FindingStatus.NEW
            and f.review_status != ReviewStatus.REJECTED
            and f.id not in worked_on
        ):
            session.delete(f)
            removed += 1
    session.flush()
    _store_kpis(session, ctx.tenant_id, kpis, today)
    trend.record_week(session, ctx.tenant_id, today)
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="analytics.run",
        payload={"created": created, "updated": updated, "removed": removed},
    )
    return RunResult(created, updated, removed, len(drafts))
