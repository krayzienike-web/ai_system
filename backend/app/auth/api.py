from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.core.deps import AccessDep, SessionDep
from app.core.limits import client_address, login_guard
from app.core.security import InvalidTokenError, create_token, decode_token, verify_password
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext, load_access_context
from app.tenancy.models import Restaurant, Role, User
from app.tenancy.permissions import Permission

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    # Not validated as an address: login only matches what was stored.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


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


def _peer(request: Request) -> str | None:
    return request.client.host if request.client else None


def _tokens(ctx: AccessContext) -> TokenPair:
    return TokenPair(
        access_token=create_token(ctx.user_id, ctx.tenant_id, "access"),
        refresh_token=create_token(ctx.user_id, ctx.tenant_id, "refresh"),
    )


@router.post("/login")
def login(body: LoginRequest, request: Request, session: SessionDep) -> TokenPair:
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
    audit(session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, action="auth.login")
    session.commit()
    return _tokens(ctx)


@router.post("/refresh")
def refresh(body: RefreshRequest, session: SessionDep) -> TokenPair:
    try:
        user_id, tenant_id = decode_token(body.refresh_token, "refresh")
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия закончилась — войдите снова"
        ) from None
    ctx = load_access_context(session, user_id, tenant_id)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия закончилась — войдите снова"
        )
    return _tokens(ctx)


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
    )
