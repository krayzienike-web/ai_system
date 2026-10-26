"""Manual review of engine findings: HQ checks a finding against the data before a director sees it."""

from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from app.insights.models import Finding, ReviewStatus
from app.overview import trend
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission


class Verdict(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    REOPEN = "reopen"  # back to «на проверке»


class RejectReason(StrEnum):
    DATA = "data"  # the uploaded data is wrong or incomplete
    LOGIC = "logic"  # the engine's rule or formula is wrong
    FALSE_ALARM = "false_alarm"  # the numbers are right, but it is not a problem (known, agreed, seasonal)
    OTHER = "other"


def review(
    session: Session,
    ctx: AccessContext,
    finding_id: UUID,
    verdict: Verdict,
    *,
    reason: RejectReason | None,
    note: str | None,
    today: date,
) -> Finding:
    if not ctx.can(Permission.FINDINGS_REVIEW):
        raise ForbiddenError("Находки проверяет управляющая компания")
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("Finding not found")
    if finding.review_status is None:
        raise ConflictError("Эта находка заведена вручную, проверка не нужна")
    note = (note or "").strip() or None
    if verdict is Verdict.REJECT:
        if reason is None:
            raise InvalidError("Укажите, что не так: данные, логика расчета или это не проблема")
        if reason in (RejectReason.LOGIC, RejectReason.OTHER) and not note:
            raise InvalidError("Опишите, что не так, — по этому описанию поправим движок")
    finding.review_status = {
        Verdict.CONFIRM: ReviewStatus.CONFIRMED,
        Verdict.REJECT: ReviewStatus.REJECTED,
        Verdict.REOPEN: ReviewStatus.PENDING,
    }[verdict]
    finding.review_reason = reason if verdict is Verdict.REJECT else None
    finding.review_note = note
    finding.reviewed_by = None if verdict is Verdict.REOPEN else ctx.user_id
    finding.reviewed_on = None if verdict is Verdict.REOPEN else today
    session.flush()
    # What the restaurants see has changed: the week's point of the trend follows.
    trend.record_week(session, ctx.tenant_id, today)
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action=f"finding.review.{verdict}",
        entity="finding",
        entity_id=finding.id,
        payload={"reason": reason, "note": note},
    )
    return finding
