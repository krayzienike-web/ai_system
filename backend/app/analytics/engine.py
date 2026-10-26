"""One run of the engine: facts → metrics → detectors → findings (docs/02 «Пересчет», docs/12).

Idempotent: a finding is matched to its draft by `key`. A re-run updates numbers and texts and keeps the
status and the work (tasks, checks). A finding that is no longer detected disappears only if nobody has
started working on it; otherwise it stays as it is for a person to close.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import m1, m2, m3
from app.analytics.costs import CostBook
from app.analytics.drafts import Draft
from app.analytics.facts import Facts, load_facts
from app.analytics.usage import Usage
from app.core.errors import ForbiddenError
from app.experiments.models import Experiment
from app.insights.models import Finding, FindingStatus, ReviewStatus
from app.norms.service import Norms, load_norms
from app.tasks.models import Task
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission

ALGORITHM_VERSION = "engine-1"
MODULES = ("M1", "M2", "M3")  # modules this version runs; findings of other modules are left alone


@dataclass(frozen=True)
class RunResult:
    created: int
    updated: int
    removed: int
    drafts: int


def detect(facts: Facts, norms: Norms) -> list[Draft]:
    usage = Usage(facts)
    costs = CostBook(facts.receipts)
    return (
        m1.detect(facts, m1.rows(facts, usage, costs), norms)
        + m2.detect(facts, norms)
        + m3.detect(facts)
        + m3.detect_contracts(facts)
        + m3.detect_network_growth(facts)
    )


def run(session: Session, ctx: AccessContext, today: date) -> RunResult:
    if not ctx.can(Permission.ANALYTICS_RUN) or not ctx.role.is_hq:
        raise ForbiddenError("Пересчет находок запускает администратор управляющей компании")
    norms = load_norms(session)
    drafts = detect(load_facts(session), norms)
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
        f.restaurant_id = d.restaurant
        f.module, f.kind, f.process = d.module, d.kind, d.process
        f.title, f.headline = d.title, d.headline
        f.effect_rub_month, f.effect_note = d.effect_rub_month, d.effect_note
        f.confidence, f.period_from, f.period_to = d.confidence, d.period_from, d.period_to
        f.actions, f.evidence = d.actions, d.evidence
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
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="analytics.run",
        payload={"created": created, "updated": updated, "removed": removed},
    )
    return RunResult(created, updated, removed, len(drafts))
