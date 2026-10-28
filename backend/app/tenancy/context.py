from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import RlsContext, apply_rls_context, get_sessionmaker
from app.tenancy.models import Role, RoleAssignment, User
from app.tenancy.permissions import ROLE_PERMISSIONS, Permission


@dataclass(frozen=True)
class AccessContext:
    user_id: UUID
    tenant_id: UUID
    role: Role
    restaurant_id: UUID | None

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def to_rls(self) -> RlsContext:
        return RlsContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            scope_all=self.role.is_hq,
            restaurant_ids=frozenset({self.restaurant_id}) if self.restaurant_id else frozenset(),
        )


def load_access_context(session: Session, user_id: UUID, tenant_id: UUID) -> AccessContext | None:
    """Resolves the user's role from the database (not from the token, so revocation is immediate)
    and applies the resulting RLS scope to the session's transaction."""
    # Narrowest scope first: the user may read only their own user and role rows.
    apply_rls_context(session, RlsContext(tenant_id=tenant_id, user_id=user_id, scope_all=False))
    row = session.execute(
        select(User.is_active, RoleAssignment.role, RoleAssignment.restaurant_id)
        .join(RoleAssignment, RoleAssignment.user_id == User.id)
        .where(User.id == user_id)
    ).one_or_none()
    if row is None or not row.is_active:
        return None
    ctx = AccessContext(
        user_id=user_id, tenant_id=tenant_id, role=Role(row.role), restaurant_id=row.restaurant_id
    )
    apply_rls_context(session, ctx.to_rls())
    return ctx


def system_context(session: Session, tenant_id: UUID) -> AccessContext:
    """The network's own background work (the engine after an upload): HQ-wide scope, no person behind it.
    Applies the scope to the session's current transaction; call again after every commit."""
    ctx = AccessContext(user_id=SYSTEM_USER, tenant_id=tenant_id, role=Role.HQ_ADMIN, restaurant_id=None)
    apply_rls_context(session, ctx.to_rls())
    return ctx


SYSTEM_USER = UUID(int=0)  # no such user: audit rows of background work have no person


@contextmanager
def tool_session(user_id: UUID, tenant_id: UUID) -> Iterator[tuple[Session, AccessContext]]:
    """One call of the assistant's tool: its own short read-only transaction under this user's row-level
    security (architecture review 27.10.2026, p. 20).

    The role is read from the database again, so access revoked during a conversation stops the next call; the
    transaction is read-only, so a tool can show data but never change it (actions go through the screens and
    a person's approval, CLAUDE.md principle 5). The context ends with the transaction: nothing carries over
    to the next call or to another user's session from the pool."""
    with get_sessionmaker()() as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        ctx = load_access_context(session, user_id, tenant_id)
        if ctx is None:
            raise PermissionError("Пользователь не найден или отключен")
        yield session, ctx
