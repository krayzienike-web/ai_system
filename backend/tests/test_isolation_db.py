"""Data isolation enforced by PostgreSQL itself (row-level security), independent of API code.

These tests connect as the application role and set the RLS context by hand, the way a buggy
endpoint might, to prove the database refuses to return or write foreign rows.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text
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
