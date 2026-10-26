"""Management commands:

- `python -m app.cli seed-demo [--password ...]` — demo tenant, 3 restaurants, users and a small work loop;
- `python -m app.cli generate-demo --out DIR [--seed N]` — files of the synthetic 12-restaurant network;
- `python -m app.cli load-demo [--seed N]` — load that network into the demo tenant via the import pipeline
  and compute findings;
- `python -m app.cli analyze` — recompute findings of the demo tenant (analytics engine).
"""

import argparse
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analytics import engine
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import hash_password
from app.demo.generator import generate
from app.demo.loader import load
from app.experiments.models import Experiment
from app.insights.models import Finding
from app.tasks.models import Task
from app.tenancy.context import load_access_context
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
        restaurants: dict[str, UUID] = {}
        for i, (code, name, city) in enumerate(DEMO_RESTAURANTS, start=1):
            restaurant = Restaurant(tenant_id=tenant.id, code=code, name=name, city=city)
            session.add(restaurant)
            session.flush()
            restaurants[code] = restaurant.id
            add_user(f"director{i}@demo.local", f"Директор {code}", Role.RESTAURANT_DIRECTOR, restaurant)
        seed_work(session, tenant.id, restaurants, date.today())
        print(f"Password for all demo users: {password}")
    engine.dispose()


def seed_work(session: Session, tenant_id: UUID, r: dict[str, UUID], today: date) -> None:
    """A few findings, checks and tasks to click the work loop through before the analytics engine exists.

    Dates are relative to today, so the demo never goes stale.
    """

    def day(offset: int) -> date:
        return today + timedelta(days=offset)

    def finding(
        code: str | None,
        kind: str,
        process: str,
        title: str,
        effect: str | None,
        actions: list[str],
        key: str | None = None,
    ) -> Finding:
        # The key is the one the analytics engine gives the same problem: its run takes these findings over.
        f = Finding(
            key=key,
            tenant_id=tenant_id,
            restaurant_id=r[code] if code else None,
            kind=kind,
            process=process,
            title=title,
            effect_rub_month=Decimal(effect) if effect else None,
            effect_note=None if effect else "искажает фудкост сети",
            actions=actions,
            found_on=day(-22),
        )
        session.add(f)
        session.flush()
        return f

    moz = finding(
        "R01",
        "problem",
        "production",
        "Перерасход моцареллы по ТТК",
        "38000",
        ["Взвешивать сыр на раздаче", "Фото-стандарт порции"],
        "M1:R01:P01",
    )
    beef = finding(
        "R02",
        "problem",
        "purchasing",
        "Говядина дороже среднего по сети",
        "31000",
        ["Заказывать заранее у основного поставщика"],
        "M3:R02:P08",
    )
    salmon = finding(
        "R03",
        "problem",
        "production",
        "Перерасход лосося по ТТК",
        "27000",
        ["Проверить выход при разделке"],
        "M1:R03:P09",
    )
    finding(
        None,
        "problem",
        "accounting",
        "ТТК картофеля фри, вероятно, устарела",
        None,
        ["Контрольная обжарка и новая ТТК"],
        "M1:net:P11",
    )
    moz.status, beef.status, salmon.status = "in_experiment", "new", "in_work"

    running = Experiment(
        tenant_id=tenant_id,
        finding_id=moz.id,
        title="Контрольное взвешивание сыра",
        hypothesis="Если две недели взвешивать моцареллу на раздаче, перерасход снизится с 9% до 3%.",
        metric="Расход сверх ТТК, %",
        test_restaurant_ids=[r["R01"]],
        starts_on=day(-10),
        ends_on=day(18),
        expected_rub_month=Decimal("25500"),
        status="running",
    )
    proposed = Experiment(
        tenant_id=tenant_id,
        finding_id=beef.id,
        title="Плановый заказ говядины",
        hypothesis="Если заказывать говядину заранее у основного поставщика, цена упадет до средней по сети.",
        metric="Цена говядины, ₽/кг",
        test_restaurant_ids=[r["R02"]],
        control_restaurant_ids=[r["R01"], r["R03"]],
        starts_on=day(4),
        ends_on=day(32),
        expected_rub_month=Decimal("18600"),
    )
    session.add_all([running, proposed])
    session.flush()
    session.add_all(
        [
            Task(
                tenant_id=tenant_id,
                restaurant_id=r["R01"],
                finding_id=moz.id,
                experiment_id=running.id,
                title=running.title,
                checklist=["Весы на станции пиццы", "Пересчет моцареллы каждый понедельник"],
                assigned_by="hq",
                created_on=day(-10),
                due_on=day(18),
                status="in_progress",
            ),
            Task(
                tenant_id=tenant_id,
                restaurant_id=r["R03"],
                finding_id=salmon.id,
                title="Проверить выход филе при разделке",
                assigned_by="director",
                created_on=day(-9),
                due_on=day(-3),
            ),
        ]
    )
    print("  work loop: 5 findings, 2 checks, 2 tasks")


def generate_demo(out: str, seed: int) -> None:
    net = generate(seed=seed)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in net.files.items():
        (folder / name).write_bytes(content)
    print(f"{len(net.files)} files, {len(net.anomalies)} planted anomalies → {folder}")


def load_demo(seed: int) -> None:
    """Loads the synthetic network into the demo tenant as its HQ admin, with row-level security on."""
    owner = create_engine(get_settings().migrations_database_url)
    with Session(owner) as session:
        admin = session.execute(select(User).where(User.email == "admin@demo.local")).scalar_one_or_none()
        if admin is None:
            raise SystemExit("Run seed-demo first")
        user_id, tenant_id = admin.id, admin.tenant_id
    owner.dispose()
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, user_id, tenant_id)
        assert ctx is not None
        rows = load(session, ctx, generate(seed=seed), today=date.today())
        result = engine.run(session, ctx, date.today())
        session.commit()
    for template, count in rows.items():
        print(f"  {template:<18} {count:>7} rows")
    print(f"  findings: {result.created} new, {result.updated} updated, {result.removed} removed")


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
        result = engine.run(session, ctx, date.today())
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
