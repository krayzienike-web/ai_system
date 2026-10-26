"""Management commands:

- `python -m app.cli seed-demo [--password ...]` — demo tenant, 3 restaurants and users;
- `python -m app.cli generate-demo --out DIR [--seed N]` — files of the synthetic 12-restaurant network;
- `python -m app.cli load-demo [--seed N]` — load that network into the demo tenant via the import pipeline,
  recompute findings week by week over the last quarter (the trend's history) and add the work on them
  (app/demo/showcase.py);
- `python -m app.cli analyze` — recompute findings of the demo tenant (analytics engine).
"""

import argparse
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analytics import engine
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import hash_password
from app.demo import showcase
from app.demo.generator import END, generate
from app.demo.loader import load
from app.tenancy.context import load_access_context
from app.tenancy.models import Restaurant, Role, RoleAssignment, Tenant, User

DEMO_TENANT = "Демо-сеть"
DEMO_TODAY = END + timedelta(days=2)  # the demo's «today»: Tuesday after the last day of data
HISTORY_WEEKS = 12
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
        restaurants: dict[str, UUID] = {}
        for i, (code, name, city) in enumerate(DEMO_RESTAURANTS, start=1):
            restaurant = Restaurant(tenant_id=tenant.id, code=code, name=name, city=city)
            session.add(restaurant)
            session.flush()
            restaurants[code] = restaurant.id
            add_user(f"director{i}@demo.local", f"Директор {code}", Role.RESTAURANT_DIRECTOR, restaurant)
        print(f"Password for all demo users: {password}")
    engine.dispose()


def generate_demo(out: str, seed: int) -> None:
    net = generate(seed=seed)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in net.files.items():
        (folder / name).write_bytes(content)
    print(f"{len(net.files)} files, {len(net.anomalies)} planted anomalies → {folder}")


def load_demo(seed: int) -> None:
    """Loads the synthetic network into the demo tenant as its HQ admin, with row-level security on.

    The engine then runs as it would have every Monday of the last quarter, on the data known by then, and an
    analyst confirms what it found (except the last week's findings: they wait in «Проверка находок»).
    """
    owner = create_engine(get_settings().migrations_database_url)
    with Session(owner) as session:
        admin = session.execute(select(User).where(User.email == "admin@demo.local")).scalar_one_or_none()
        analyst = session.execute(select(User).where(User.email == "analyst@demo.local")).scalar_one_or_none()
        if admin is None or analyst is None:
            raise SystemExit("Run seed-demo first")
        user_id, tenant_id, analyst_id = admin.id, admin.tenant_id, analyst.id
    owner.dispose()
    today = DEMO_TODAY
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, user_id, tenant_id)
        assert ctx is not None
        rows = load(session, ctx, generate(seed=seed), today=today)
        result = showcase.build(session, ctx, analyst_id, today, HISTORY_WEEKS)
        session.commit()
    for template, count in rows.items():
        print(f"  {template:<18} {count:>7} rows")
    print(f"  history: {HISTORY_WEEKS} weekly runs; today ({today}): {result.created} new findings")


def analyze() -> None:
    """Recomputes findings of the demo tenant as its HQ admin."""
    owner = create_engine(get_settings().migrations_database_url)
    with Session(owner) as session:
        admin = session.execute(select(User).where(User.email == "admin@demo.local")).scalar_one()
        user_id, tenant_id = admin.id, admin.tenant_id
    owner.dispose()
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, user_id, tenant_id)
        assert ctx is not None
        result = engine.run(session, ctx, DEMO_TODAY)
        session.commit()
    print(f"findings: {result.created} new, {result.updated} updated, {result.removed} removed")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-demo", help="Create the demo tenant, 3 restaurants and users")
    seed.add_argument("--password", default="demo12345")
    gen = sub.add_parser("generate-demo", help="Write the files of the synthetic demo network")
    gen.add_argument("--out", default="demo-data")
    gen.add_argument("--seed", type=int, default=42)
    ld = sub.add_parser("load-demo", help="Load the synthetic network into the demo tenant")
    ld.add_argument("--seed", type=int, default=42)
    sub.add_parser("analyze", help="Recompute findings of the demo tenant")
    args = parser.parse_args()
    if args.command == "analyze":
        analyze()
    elif args.command == "seed-demo":
        seed_demo(args.password)
    elif args.command == "generate-demo":
        generate_demo(args.out, args.seed)
    elif args.command == "load-demo":
        load_demo(args.seed)


if __name__ == "__main__":
    main()
