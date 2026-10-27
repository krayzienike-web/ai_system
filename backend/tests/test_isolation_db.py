"""Data isolation enforced by PostgreSQL itself (row-level security), independent of API code.

These tests connect as the application role and set the RLS context by hand, the way a buggy
endpoint might, to prove the database refuses to return or write foreign rows.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import RlsContext, apply_rls_context, get_sessionmaker
from tests.conftest import Network

TABLES = ["tenants", "restaurants", "users", "role_assignments", "audit_log"]


@pytest.fixture
def app_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _count(session: Session, table: str) -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


def test_app_role_cannot_bypass_rls(app_session: Session) -> None:
    row = app_session.execute(
        text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert row == (False, False)
    owners = app_session.execute(
        text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
    ).scalars()
    assert "franchise_app" not in list(owners)


def test_rls_enabled_on_every_public_table(app_session: Session) -> None:
    unprotected = app_session.execute(
        text(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity "
            "AND relname <> 'alembic_version'"
        )
    ).scalars()
    assert list(unprotected) == []


def test_no_context_sees_nothing(app_session: Session, network: Network) -> None:
    for table in TABLES:
        assert _count(app_session, table) == 0, table


def test_director_context_sees_own_rows_only(app_session: Session, network: Network) -> None:
    apply_rls_context(
        app_session,
        RlsContext(
            tenant_id=network.a.id,
            user_id=network.a.users["director1@a.ru"],
            scope_all=False,
            restaurant_ids=frozenset({network.a.restaurants["A1"]}),
        ),
    )
    assert _count(app_session, "tenants") == 1
    assert _count(app_session, "restaurants") == 1
    assert _count(app_session, "users") == 1
    assert _count(app_session, "role_assignments") == 1


def test_hq_context_limited_to_its_tenant(app_session: Session, network: Network) -> None:
    apply_rls_context(
        app_session,
        RlsContext(tenant_id=network.a.id, user_id=network.a.users["admin@a.ru"], scope_all=True),
    )
    assert _count(app_session, "restaurants") == 3
    assert _count(app_session, "users") == 5
    updated = app_session.execute(
        text("UPDATE restaurants SET name = 'hacked' WHERE id = :id"), {"id": network.b.restaurants["B1"]}
    )
    assert updated.rowcount == 0  # type: ignore[attr-defined]


def test_cannot_write_into_another_tenant(app_session: Session, network: Network) -> None:
    apply_rls_context(
        app_session,
        RlsContext(tenant_id=network.a.id, user_id=network.a.users["admin@a.ru"], scope_all=True),
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        app_session.execute(
            text("INSERT INTO restaurants (id, tenant_id, code, name) VALUES (:id, :tid, 'X', 'X')"),
            {"id": uuid4(), "tid": network.b.id},
        )


def test_director_cannot_create_restaurant_outside_scope(app_session: Session, network: Network) -> None:
    apply_rls_context(
        app_session,
        RlsContext(
            tenant_id=network.a.id,
            user_id=network.a.users["director1@a.ru"],
            scope_all=False,
            restaurant_ids=frozenset({network.a.restaurants["A1"]}),
        ),
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        app_session.execute(
            text("INSERT INTO restaurants (id, tenant_id, code, name) VALUES (:id, :tid, 'X', 'X')"),
            {"id": uuid4(), "tid": network.a.id},
        )


def test_role_scope_constraint(app_session: Session, network: Network) -> None:
    apply_rls_context(
        app_session,
        RlsContext(tenant_id=network.a.id, user_id=network.a.users["admin@a.ru"], scope_all=True),
    )
    with pytest.raises(DBAPIError, match="scope_matches_role"):
        app_session.execute(
            text(
                "INSERT INTO role_assignments (id, tenant_id, user_id, role) "
                "VALUES (:id, :tid, :uid, 'restaurant_director')"
            ),
            {"id": uuid4(), "tid": network.a.id, "uid": network.a.users["analyst@a.ru"]},
        )


def test_director_cannot_change_or_delete_network_wide_name_matches(
    app_session: Session, network: Network, owner_engine: Engine
) -> None:
    a1 = network.a.restaurants["A1"]
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO name_aliases "
                "(tenant_id, restaurant_id, kind, source_key, source_text, target_id) "
                "VALUES (:t, NULL, 'product', 'моцарелла фиор', 'Моцарелла фиор', :x), "
                "(:t, :r, 'product', 'руккола свежая', 'Руккола свежая', :x)"
            ),
            {"t": network.a.id, "r": a1, "x": uuid4()},
        )
    ctx = RlsContext(network.a.id, network.a.users["director1@a.ru"], False, frozenset({a1}))
    apply_rls_context(app_session, ctx)
    assert _count(app_session, "name_aliases") == 2  # reads network-wide and own
    moved = app_session.execute(
        text("UPDATE name_aliases SET restaurant_id = :r WHERE restaurant_id IS NULL"), {"r": a1}
    )
    deleted = app_session.execute(text("DELETE FROM name_aliases WHERE restaurant_id IS NULL"))
    assert moved.rowcount == 0 and deleted.rowcount == 0  # type: ignore[attr-defined]
    with pytest.raises(DBAPIError):
        app_session.execute(
            text(
                "INSERT INTO name_aliases "
                "(tenant_id, restaurant_id, kind, source_key, source_text, target_id) "
                "VALUES (:t, NULL, 'product', 'x', 'x', :x)"
            ),
            {"t": network.a.id, "x": uuid4()},
        )
    app_session.rollback()
    apply_rls_context(app_session, ctx)
    own = app_session.execute(text("DELETE FROM name_aliases WHERE restaurant_id = :r"), {"r": a1})
    assert own.rowcount == 1  # type: ignore[attr-defined]


def test_director_reads_but_cannot_write_network_kpis_trend_and_runs(
    app_session: Session, network: Network, owner_engine: Engine
) -> None:
    """Code review 27.10.2026: the engine and HQ write KPIs, the trend and the run log; directors read."""
    a1 = network.a.restaurants["A1"]
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO kpi_snapshots (tenant_id, restaurant_id, computed_on, revenue) "
                "VALUES (:t, NULL, '2026-10-20', 100), (:t, :r, '2026-10-20', 50)"
            ),
            {"t": network.a.id, "r": a1},
        )
        conn.execute(
            text(
                "INSERT INTO trend_points (tenant_id, restaurant_id, week_end, losses, potential, "
                "open_findings, returned) VALUES (:t, NULL, '2026-10-18', 1, 1, 1, 0)"
            ),
            {"t": network.a.id},
        )
        conn.execute(
            text("INSERT INTO analytics_runs (tenant_id, trigger, status) VALUES (:t, 'upload', 'done')"),
            {"t": network.a.id},
        )
    ctx = RlsContext(network.a.id, network.a.users["director1@a.ru"], False, frozenset({a1}))
    apply_rls_context(app_session, ctx)
    assert _count(app_session, "kpi_snapshots") == 2 and _count(app_session, "trend_points") == 1
    for statement in (
        "UPDATE kpi_snapshots SET revenue = 0",
        "DELETE FROM kpi_snapshots",
        "UPDATE trend_points SET losses = 0",
        "DELETE FROM trend_points",
        "UPDATE analytics_runs SET status = 'failed'",
        "DELETE FROM analytics_runs",
    ):
        assert app_session.execute(text(statement)).rowcount == 0, statement  # type: ignore[attr-defined]
    with pytest.raises(DBAPIError):
        app_session.execute(
            text(
                "INSERT INTO kpi_snapshots (tenant_id, restaurant_id, computed_on, revenue) "
                "VALUES (:t, NULL, '2026-10-21', 1)"
            ),
            {"t": network.a.id},
        )
    app_session.rollback()
    # Asking for a run (an upload) is allowed to everyone of the network.
    apply_rls_context(app_session, ctx)
    app_session.execute(
        text("INSERT INTO analytics_runs (tenant_id, trigger, status) VALUES (:t, 'upload', 'queued')"),
        {"t": network.a.id},
    )


def test_director_can_neither_change_a_finding_under_review_nor_see_it_through_a_task(
    app_session: Session, network: Network, owner_engine: Engine
) -> None:
    """TC-ISO-09 (docs/12, «Проверка находок»): until HQ confirms a finding, its director's database
    session does not see it — not directly, not by joining their own task — and cannot confirm it."""
    a, a1 = network.a.id, network.a.restaurants["A1"]
    pending, confirmed = uuid4(), uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO findings (id, tenant_id, restaurant_id, kind, process, title, found_on, "
                "key, module, review_status) VALUES "
                "(:p, :t, :r, 'problem', 'production', 'На проверке', '2026-10-01', "
                "'M1:A1:P1', 'M1', 'pending'), "
                "(:c, :t, :r, 'problem', 'production', 'Проверена', '2026-10-01', "
                "'M1:A1:P2', 'M1', 'confirmed')"
            ),
            {"p": pending, "c": confirmed, "t": a, "r": a1},
        )
        # A task of A1 that points at the finding under review (e.g. set before new data sent it back).
        conn.execute(
            text(
                "INSERT INTO tasks (tenant_id, restaurant_id, finding_id, title, assigned_by, "
                "created_on, due_on) "
                "VALUES (:t, :r, :p, 'Шаг', 'hq', '2026-10-02', '2026-10-30')"
            ),
            {"t": a, "r": a1, "p": pending},
        )
    ctx = RlsContext(a, network.a.users["director1@a.ru"], False, frozenset({a1}))
    apply_rls_context(app_session, ctx)
    assert _count(app_session, "findings") == 1 and _count(app_session, "tasks") == 1  # the task is theirs
    through_task = app_session.execute(
        text("SELECT f.title FROM tasks t JOIN findings f ON f.id = t.finding_id")
    ).all()
    assert through_task == []
    for statement in (
        "UPDATE findings SET review_status = 'confirmed' WHERE id = :p",
        "UPDATE findings SET effect_rub_month = 0 WHERE id = :p",
        "DELETE FROM findings WHERE id = :p",
    ):
        changed = app_session.execute(text(statement), {"p": pending})
        assert changed.rowcount == 0, statement  # type: ignore[attr-defined]
    # Nor can a director send their checked finding back under review (it would vanish from their view).
    with pytest.raises(DBAPIError):
        app_session.execute(
            text("UPDATE findings SET review_status = 'pending' WHERE id = :c"), {"c": confirmed}
        )
    app_session.rollback()
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, review_status FROM findings ORDER BY title")).all()
    assert sorted((str(i), s) for i, s in rows) == sorted(
        [(str(pending), "pending"), (str(confirmed), "confirmed")]
    )


def test_the_application_can_only_add_to_the_audit_log(app_session: Session) -> None:
    """Architecture review 27.10.2026, p. 7: nobody erases or rewrites the log through the application."""
    granted = app_session.execute(
        text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'audit_log' AND grantee = current_user"
        )
    ).scalars()
    assert sorted(granted) == ["INSERT", "SELECT"]
