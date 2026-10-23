from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.security import InvalidTokenError, decode_token
from app.tenancy.context import AccessContext, load_access_context
from app.tenancy.permissions import Permission

_bearer = HTTPBearer(auto_error=False)


def get_session() -> Iterator[Session]:
    """One transaction per request. Write endpoints commit explicitly before returning,
    so that a failed commit is reported to the client; anything uncommitted is rolled back."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_access_context(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AccessContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        user_id, tenant_id = decode_token(credentials.credentials, "access")
    except InvalidTokenError:
        raise unauthorized from None
    ctx = load_access_context(session, user_id, tenant_id)
    if ctx is None:
        raise unauthorized
    return ctx


AccessDep = Annotated[AccessContext, Depends(get_access_context)]


def require(permission: Permission) -> Callable[[AccessContext], AccessContext]:
    def dependency(ctx: AccessDep) -> AccessContext:
        if not ctx.can(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return ctx

    return dependency
