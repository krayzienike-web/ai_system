"""Sign-in sessions (pre-pilot review 10.11.2026, p. 5; docs/09 «Сессия»).

A sign-in is a family of refresh tokens. The token itself lives only in the browser's httpOnly cookie; the
database keeps its SHA-256. Every refresh replaces the token with a new one of the same family:
- a replaced token presented again within `GRACE` (two tabs refreshing at once) gets a new token too;
- presented later, it was stolen or copied: the whole family is revoked and both holders sign in again;
- signing out revokes the family, a new password revokes all of the user's families.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, select, text, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_settings
from app.core.models import Base, IdMixin, TenantMixin
from app.tenancy.context import AccessContext, load_access_context

GRACE = timedelta(seconds=30)


class AuthSession(IdMixin, TenantMixin, Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionEnded(Exception):
    """The token is unknown, expired, revoked or reused: the person signs in again."""


@dataclass(frozen=True)
class Refreshed:
    ctx: AccessContext
    token: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue(session: Session, ctx: AccessContext, family_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            family_id=family_id,
            token_hash=_hash(token),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_ttl_days),
        )
    )
    session.flush()
    return token


def start(session: Session, ctx: AccessContext) -> str:
    """A new sign-in: the first token of a new family."""
    return _issue(session, ctx, uuid4())


def _find(session: Session, token: str) -> tuple[AuthSession, AccessContext]:
    """The token's row under its user's row-level security; the user must still be active."""
    found = session.execute(
        text("SELECT session_id, user_id, tenant_id FROM app.auth_lookup_session(:h)"), {"h": _hash(token)}
    ).one_or_none()
    if found is None:
        raise SessionEnded
    ctx = load_access_context(session, found.user_id, found.tenant_id)
    if ctx is None:  # the user was disabled
        raise SessionEnded
    row = session.get(AuthSession, found.session_id, with_for_update=True)
    if row is None:
        raise SessionEnded
    return row, ctx


def _revoke_family(session: Session, family_id: UUID, now: datetime) -> None:
    session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def rotate(session: Session, token: str) -> Refreshed:
    """The next token of the sign-in. The caller commits, also when SessionEnded is raised: a reused token
    revokes its family for good."""
    row, ctx = _find(session, token)
    now = datetime.now(UTC)
    if row.revoked_at is not None or row.expires_at <= now:
        raise SessionEnded
    if row.rotated_at is not None and now - row.rotated_at > GRACE:
        _revoke_family(session, row.family_id, now)
        raise SessionEnded
    if row.rotated_at is None:
        row.rotated_at = now
    return Refreshed(ctx, _issue(session, ctx, row.family_id))


def end(session: Session, token: str) -> AccessContext | None:
    """Signing out: the sign-in's whole family is revoked. An unknown token changes nothing."""
    try:
        row, ctx = _find(session, token)
    except SessionEnded:
        return None
    _revoke_family(session, row.family_id, datetime.now(UTC))
    return ctx


def end_all(session: Session, user_id: UUID) -> int:
    """Every sign-in of the user (a new password, the account disabled). Under the user's own row-level
    security, or as the schema owner from the command line."""
    result = session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return int(getattr(result, "rowcount", 0) or 0)


def active(session: Session, user_id: UUID) -> int:
    now = datetime.now(UTC)
    return len(
        session.execute(
            select(AuthSession.id).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.rotated_at.is_(None),
                AuthSession.expires_at > now,
            )
        ).all()
    )
