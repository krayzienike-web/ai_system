"""The pilot's accounts, managed by the operator from the command line (stage 8, step 7; pre-pilot review
10.11.2026, p. 4; docs/09 «Учетные записи»).

Every person has their own login: the operator creates it with a generated password, hands it over, and the
person changes it at the first sign-in. Disabling a login or resetting its password ends all of its sign-ins.
Runs as the schema owner, like migrations: the tenant does not exist yet, or the operator is nobody's user.
"""

import secrets
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from app.auth import sessions
from app.core.config import get_settings
from app.core.security import hash_password
from app.tenancy.models import Restaurant, Role, RoleAssignment, Tenant, User

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read out over the phone


class AccountError(Exception):
    """The operator's mistake: said in plain words, nothing changed."""


@dataclass(frozen=True)
class Issued:
    email: str
    password: str


def new_password() -> str:
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4))


def _owner() -> Engine:
    return create_engine(get_settings().migrations_database_url)


def _user(session: Session, email: str) -> User:
    user = session.execute(
        select(User).where(func.lower(User.email) == email.strip().lower())
    ).scalar_one_or_none()
    if user is None:
        raise AccountError(f"Нет пользователя {email}")
    return user


def create_tenant(name: str, admin_email: str, admin_name: str) -> Issued:
    """A network with its first HQ admin. Not on the demo stand: a real network lives apart from the demo
    calendar and its nightly rebuild (pre-pilot review, p. 4а)."""
    if get_settings().is_demo_stand:
        raise AccountError(
            "Это демо-стенд (FAI_DEMO_TODAY, FAI_DEMO_RESET_NIGHTLY): настоящую сеть заводят в конфигурации "
            "пилота (deploy/README.md, «Пилот»)"
        )
    engine = _owner()
    try:
        with Session(engine) as session, session.begin():
            if session.execute(select(Tenant).where(Tenant.name == name)).scalar_one_or_none():
                raise AccountError(f"Сеть «{name}» уже есть")
            tenant = Tenant(name=name)
            session.add(tenant)
            session.flush()
            return _add(session, tenant, admin_email, admin_name, Role.HQ_ADMIN, None)
    finally:
        engine.dispose()


def add_user(tenant_name: str, email: str, full_name: str, role: Role, restaurant_code: str | None) -> Issued:
    """A login in the network. A director needs their restaurant (loaded with «Рестораны» first); HQ roles
    take none."""
    engine = _owner()
    try:
        with Session(engine) as session, session.begin():
            tenant = session.execute(select(Tenant).where(Tenant.name == tenant_name)).scalar_one_or_none()
            if tenant is None:
                raise AccountError(f"Нет сети «{tenant_name}»")
            restaurant = None
            if role is Role.RESTAURANT_DIRECTOR:
                if not restaurant_code:
                    raise AccountError("Директору нужен ресторан: --restaurant КОД")
                restaurant = session.execute(
                    select(Restaurant).where(
                        Restaurant.tenant_id == tenant.id, Restaurant.code == restaurant_code
                    )
                ).scalar_one_or_none()
                if restaurant is None:
                    raise AccountError(
                        f"В сети «{tenant_name}» нет ресторана {restaurant_code}: загрузите справочник "
                        "«Рестораны»"
                    )
            elif restaurant_code:
                raise AccountError("Ресторан указывают только директору: УК видит всю сеть")
            return _add(session, tenant, email, full_name, role, restaurant)
    finally:
        engine.dispose()


def _add(
    session: Session, tenant: Tenant, email: str, full_name: str, role: Role, restaurant: Restaurant | None
) -> Issued:
    email = email.strip()
    if "@" not in email or len(email) > 320:
        raise AccountError(f"Не похоже на email: {email}")
    if session.execute(select(User.id).where(func.lower(User.email) == email.lower())).scalar_one_or_none():
        raise AccountError(f"Пользователь {email} уже есть")
    password = new_password()
    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=full_name.strip()[:200],
        password_hash=hash_password(password),
        must_change_password=True,
    )
    session.add(user)
    session.flush()
    session.add(
        RoleAssignment(
            tenant_id=tenant.id,
            user_id=user.id,
            role=role,
            restaurant_id=restaurant.id if restaurant else None,
        )
    )
    return Issued(email, password)


def set_active(email: str, active: bool) -> int:
    """Disables or enables a login; disabling ends its sign-ins (the access token stops at the next request:
    every request reads `is_active`). Returns how many sign-ins ended."""
    engine = _owner()
    try:
        with Session(engine) as session, session.begin():
            user = _user(session, email)
            user.is_active = active
            return 0 if active else sessions.end_all(session, user.id)
    finally:
        engine.dispose()


def reset_password(email: str) -> Issued:
    """A new handed-out password: to be changed at the next sign-in; every sign-in of the login ends."""
    engine = _owner()
    try:
        with Session(engine) as session, session.begin():
            user = _user(session, email)
            password = new_password()
            user.password_hash = hash_password(password)
            user.must_change_password = True
            sessions.end_all(session, user.id)
            return Issued(user.email, password)
    finally:
        engine.dispose()


def users(tenant_name: str) -> list[tuple[str, str, str, str | None, bool]]:
    """(email, full name, role, restaurant code, active) of the network's logins."""
    engine = _owner()
    try:
        with Session(engine) as session:
            tenant = session.execute(select(Tenant).where(Tenant.name == tenant_name)).scalar_one_or_none()
            if tenant is None:
                raise AccountError(f"Нет сети «{tenant_name}»")
            rows = session.execute(
                select(User.email, User.full_name, RoleAssignment.role, Restaurant.code, User.is_active)
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .outerjoin(Restaurant, Restaurant.id == RoleAssignment.restaurant_id)
                .where(User.tenant_id == tenant.id)
                .order_by(RoleAssignment.role, User.email)
            ).all()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    finally:
        engine.dispose()
