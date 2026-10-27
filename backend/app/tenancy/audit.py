from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.tenancy.context import SYSTEM_USER
from app.tenancy.models import AuditLog


def audit(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    action: str,
    entity: str | None = None,
    entity_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=None if user_id == SYSTEM_USER else user_id,  # background work: no person
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload or {},
        )
    )
