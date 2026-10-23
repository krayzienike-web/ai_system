from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import SessionDep, require
from app.core.security import hash_password
from app.tenancy.audit import audit
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant, Role, RoleAssignment, User
from app.tenancy.permissions import Permission

router = APIRouter(tags=["tenancy"])

CanReadRestaurants = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_READ))]
CanManageRestaurants = Annotated[AccessContext, Depends(require(Permission.RESTAURANTS_MANAGE))]
CanManageUsers = Annotated[AccessContext, Depends(require(Permission.USERS_MANAGE))]


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    city: str | None
    format: str | None
    opened_on: date | None


class RestaurantIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    city: str | None = None
    format: str | None = None
    opened_on: date | None = None


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    role: Role
    restaurant_id: UUID | None = None

    @model_validator(mode="after")
    def scope_matches_role(self) -> "UserIn":
        if (self.role == Role.RESTAURANT_DIRECTOR) != (self.restaurant_id is not None):
            raise ValueError("restaurant_id is required for a director and forbidden for HQ roles")
        return self


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    role: Role
    restaurant_id: UUID | None


@router.get("/restaurants")
def list_restaurants(ctx: CanReadRestaurants, session: SessionDep) -> list[RestaurantOut]:
    # Row-level security already limits rows to the caller's scope.
    rows = session.execute(select(Restaurant).order_by(Restaurant.code)).scalars()
    return [RestaurantOut.model_validate(r) for r in rows]


@router.get("/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: UUID, ctx: CanReadRestaurants, session: SessionDep) -> RestaurantOut:
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return RestaurantOut.model_validate(restaurant)


@router.post("/restaurants", status_code=status.HTTP_201_CREATED)
def create_restaurant(body: RestaurantIn, ctx: CanManageRestaurants, session: SessionDep) -> RestaurantOut:
    restaurant = Restaurant(tenant_id=ctx.tenant_id, **body.model_dump())
    session.add(restaurant)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Restaurant code exists") from None
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="restaurant.create",
        entity="restaurant",
        entity_id=restaurant.id,
        payload={"code": restaurant.code},
    )
    out = RestaurantOut.model_validate(restaurant)
    session.commit()
    return out


@router.get("/users")
def list_users(ctx: CanManageUsers, session: SessionDep) -> list[UserOut]:
    rows = session.execute(
        select(User, RoleAssignment)
        .join(RoleAssignment, RoleAssignment.user_id == User.id)
        .order_by(User.email)
    ).all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            role=Role(ra.role),
            restaurant_id=ra.restaurant_id,
        )
        for u, ra in rows
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, ctx: CanManageUsers, session: SessionDep) -> UserOut:
    if body.restaurant_id is not None and session.get(Restaurant, body.restaurant_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown restaurant")
    email_taken = session.execute(
        select(func.count()).select_from(User).where(func.lower(User.email) == body.email.lower())
    ).scalar_one()
    if email_taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        tenant_id=ctx.tenant_id,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    try:
        session.add(user)
        session.flush()
        session.add(
            RoleAssignment(
                tenant_id=ctx.tenant_id, user_id=user.id, role=body.role, restaurant_id=body.restaurant_id
            )
        )
        session.flush()
    except IntegrityError:
        # Email unique across tenants: another tenant may own it (invisible to us through RLS).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
    audit(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="user.create",
        entity="user",
        entity_id=user.id,
        payload={"role": body.role, "restaurant_id": str(body.restaurant_id) if body.restaurant_id else None},
    )
    out = UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=True,
        role=body.role,
        restaurant_id=body.restaurant_id,
    )
    session.commit()
    return out
