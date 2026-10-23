from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()
# Verified against when the user does not exist, so that response time does not reveal valid emails.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_token(user_id: UUID, tenant_id: UUID, token_type: TokenType) -> str:
    settings = get_settings()
    ttl = (
        timedelta(minutes=settings.access_token_ttl_minutes)
        if token_type == "access"  # noqa: S105
        else timedelta(days=settings.refresh_token_ttl_days)
    )
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "tid": str(tenant_id), "typ": token_type, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> tuple[UUID, UUID]:
    """Returns (user_id, tenant_id)."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != expected_type:
            raise InvalidTokenError("wrong token type")
        return UUID(payload["sub"]), UUID(payload["tid"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
