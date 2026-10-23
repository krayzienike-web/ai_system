"""Management commands: `python -m app.cli seed-demo [--password ...]`."""

import argparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.tenancy.models import Restaurant, Role, RoleAssignment, Tenant, User

DEMO_TENANT = "Демо-сеть"
DEMO_RESTAURANTS = [
    ("R01", "Ресторан на Тверской", "Москва"),
    ("R02", "Ресторан на Арбате", "Москва"),
    ("R03", "Ресторан на Невском", "Санкт-Петербург"),
]


def seed_demo(password: str) -> None:
    # Seeding runs as the schema owner (outside RLS), like migrations.
    engine = create_engine(get_settings().migrations_database_url)
    with Session(engine) as session, session.begin():
        if session.execute(select(Tenant).where(Tenant.name == DEMO_TENANT)).scalar_one_or_none():
            print("Demo tenant already exists, nothing to do.")
            return
        tenant = Tenant(name=DEMO_TENANT)
        session.add(tenant)
        session.flush()

        def add_user(email: str, name: str, role: Role, restaurant: Restaurant | None = None) -> None:
            user = User(
                tenant_id=tenant.id, email=email, full_name=name, password_hash=hash_password(password)
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
            print(f"  {email:<28} {role}")

        print(f"Tenant: {DEMO_TENANT}")
        add_user("admin@demo.local", "Администратор УК", Role.HQ_ADMIN)
        add_user("analyst@demo.local", "Аналитик УК", Role.HQ_ANALYST)
        for i, (code, name, city) in enumerate(DEMO_RESTAURANTS, start=1):
            restaurant = Restaurant(tenant_id=tenant.id, code=code, name=name, city=city)
            session.add(restaurant)
            session.flush()
            add_user(f"director{i}@demo.local", f"Директор {code}", Role.RESTAURANT_DIRECTOR, restaurant)
        print(f"Password for all demo users: {password}")
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-demo", help="Create the demo tenant, 3 restaurants and users")
    seed.add_argument("--password", default="demo12345")
    args = parser.parse_args()
    if args.command == "seed-demo":
        seed_demo(args.password)


if __name__ == "__main__":
    main()
