from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.auth import sessions
from app.core.config import get_settings
from app.core.deps import AccessDep, SessionDep
from app.core.limits import client_address, login_guard
from app.core.security import create_token, hash_password, verify_password
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext, load_access_context
from app.tenancy.models import Restaurant, Role, User
from app.tenancy.permissions import Permission

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    # Not validated as an address: login only matches what was stored.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=200)


REFRESH_COOKIE = "fai_refresh"
COOKIE_PATH = "/api/auth"  # the cookie goes only to signing in, refreshing and out
MIN_PASSWORD = 10


class AccessToken(BaseModel):
    """The access token goes to the page's memory, the refresh token only to an httpOnly cookie (review,
    p. 5)."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105
    must_change_password: bool = False


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class RestaurantRef(BaseModel):
    id: UUID
    code: str
    name: str


class Me(BaseModel):
    id: UUID
    email: str
    full_name: str
    tenant_id: UUID
    role: Role
    restaurant: RestaurantRef | None
    permissions: list[Permission]
    must_change_password: bool


def _peer(request: Request) -> str | None:
    return request.client.host if request.client else None


SESSION_ENDED = "Сессия закончилась — войдите снова"


def _signed_in(response: Response, ctx: AccessContext, refresh_token: str) -> AccessToken:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path=COOKIE_PATH,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    return AccessToken(
        access_token=create_token(ctx.user_id, ctx.tenant_id, "access"),
        must_change_password=ctx.must_change_password,
    )


def _signed_out(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=COOKIE_PATH, secure=settings.secure_cookies, httponly=True, samesite="strict"
    )


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, session: SessionDep) -> AccessToken:
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    # Failed attempts per email and per address; argon2 checks at once are bounded (pre-pilot review, p. 3).
    keys = (
        f"email:{body.email.strip().lower()}",
        f"ip:{client_address(dict(request.headers), _peer(request))}",
    )
    login_guard.check(*keys)
    # Runs before any tenant is known, so it goes through a narrow SECURITY DEFINER function.
    row = session.execute(
        text("SELECT user_id, tenant_id, password_hash, is_active FROM app.auth_lookup_user(:email)"),
        {"email": body.email},
    ).one_or_none()
    with login_guard.hashing():
        valid = verify_password(body.password, row.password_hash if row else None)
    if not valid or row is None:
        login_guard.failed(*keys)
        raise invalid
    ctx = load_access_context(session, row.user_id, row.tenant_id)
    if ctx is None:
        login_guard.failed(*keys)
        raise invalid
    login_guard.succeeded(keys[0])
    refresh_token = sessions.start(session, ctx)
    audit(session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, action="auth.login")
    session.commit()
    return _signed_in(response, ctx, refresh_token)


@router.post("/refresh")
def refresh(response: Response, session: SessionDep, token: RefreshCookie = None) -> AccessToken:
    """A new access token for the cookie's sign-in, and the cookie's next token."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SESSION_ENDED)
    try:
        refreshed = sessions.rotate(session, token)
    except sessions.SessionEnded:
        session.commit()  # a reused token revoked its sign-in: that stays
        _signed_out(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=SESSION_ENDED,
            headers={"Set-Cookie": response.headers["set-cookie"]},
        ) from None
    session.commit()
    return _signed_in(response, refreshed.ctx, refreshed.token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session: SessionDep, token: RefreshCookie = None) -> None:
    """Signing out on this device: the sign-in is revoked, the cookie removed. Without a valid cookie it
    just removes the cookie."""
    if token:
        ctx = sessions.end(session, token)
        if ctx is not None:
            audit(session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, action="auth.logout")
        session.commit()
    _signed_out(response)


@router.post("/password")
def change_password(
    body: PasswordChange, ctx: AccessDep, response: Response, session: SessionDep
) -> AccessToken:
    """The person's own new password: every other sign-in of theirs ends, this one gets a new token."""
    key = f"user:{ctx.user_id}"
    login_guard.check(key)
    user = session.execute(select(User).where(User.id == ctx.user_id)).scalar_one()
    with login_guard.hashing():
        valid = verify_password(body.current_password, user.password_hash)
    if not valid:
        login_guard.failed(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль указан неверно")
    if len(body.new_password) < MIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Новый пароль должен быть не короче {MIN_PASSWORD} символов",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Новый пароль должен отличаться от текущего"
        )
    login_guard.succeeded(key)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    sessions.end_all(session, ctx.user_id)
    session.flush()
    fresh = load_access_context(session, ctx.user_id, ctx.tenant_id)
    assert fresh is not None
    refresh_token = sessions.start(session, fresh)
    audit(session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, action="auth.password_changed")
    session.commit()
    return _signed_in(response, fresh, refresh_token)


@router.get("/me")
def me(ctx: AccessDep, session: SessionDep) -> Me:
    user = session.execute(select(User).where(User.id == ctx.user_id)).scalar_one()
    restaurant = (
        session.execute(select(Restaurant).where(Restaurant.id == ctx.restaurant_id)).scalar_one_or_none()
        if ctx.restaurant_id
        else None
    )
    return Me(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        restaurant=RestaurantRef(id=restaurant.id, code=restaurant.code, name=restaurant.name)
        if restaurant
        else None,
        permissions=sorted(ctx.permissions),
        must_change_password=ctx.must_change_password,
    )
