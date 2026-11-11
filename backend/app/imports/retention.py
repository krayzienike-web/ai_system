"""How long the source files are kept (pre-pilot review 10.11.2026, p. 18; docs/04 «Хранение файлов»; Q37).

An uploaded file holds the network's raw data, often with people's names in it. Past its period the file's
bytes are deleted; the batch stays with its report, and the data loaded from it stays too:
- a file that failed the check — after `FAI_FILE_RETENTION_FAILED_DAYS` (7): it was never loaded;
- any other — after `FAI_FILE_RETENTION_DAYS` (90). Such a batch can no longer be re-processed, and a
  rollback that would rebuild its period from it says so (imports/service.py, `_source`).
The worker runs it every night; `python -m app.cli purge-files` does it by hand. Safe twice.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.imports.models import BatchStatus, ImportBatch
from app.tenancy.audit import audit
from app.tenancy.context import system_context


def purge(session: Session, tenant_id: UUID, now: datetime) -> int:
    """Deletes the network's source files past their period; returns how many."""
    settings = get_settings()
    failed_before = now - timedelta(days=settings.file_retention_failed_days)
    others_before = now - timedelta(days=settings.file_retention_days)
    ctx = system_context(session, tenant_id)
    result = session.execute(
        update(ImportBatch)
        .where(
            ImportBatch.raw_deleted_at.is_(None),
            or_(
                and_(ImportBatch.status == BatchStatus.FAILED, ImportBatch.created_at < failed_before),
                ImportBatch.created_at < others_before,
            ),
        )
        .values(raw=b"", raw_deleted_at=now)
    )
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        audit(
            session,
            tenant_id=ctx.tenant_id,
            user_id=None,
            action="import.files_purged",
            payload={"files": count},
        )
    return count


def purge_all(today: date | None = None) -> int:
    """Every network, each in a transaction of its own. `today` is unused: the periods count from now."""
    del today
    now = datetime.now(UTC)
    with get_sessionmaker()() as session:
        tenants = list(session.execute(text("SELECT app.tenant_ids()")).scalars())
    total = 0
    for tenant_id in tenants:
        with get_sessionmaker()() as session:
            total += purge(session, tenant_id, now)
            session.commit()
    return total
