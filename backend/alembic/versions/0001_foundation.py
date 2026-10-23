"""Foundation: tenants, restaurants, users, roles, audit log, row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls
from app.core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _ts() -> sa.Column[sa.DateTime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tenant_fk() -> sa.Column[UUID]:
    return sa.Column(
        "tenant_id",
        UUID,
        sa.ForeignKey("tenants.id", ondelete="CASCADE", name=None),
        nullable=False,
        index=True,
    )


def upgrade() -> None:
    app_role = get_settings().app_db_role

    # --- RLS context functions -------------------------------------------------------------
    op.execute("CREATE SCHEMA app")
    op.execute(
        """
        CREATE FUNCTION app.current_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

        CREATE FUNCTION app.current_user_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

        CREATE FUNCTION app.scope_all() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.scope_all', true), 'off') = 'on' $$;

        CREATE FUNCTION app.current_restaurant_ids() RETURNS uuid[] LANGUAGE sql STABLE AS
        $$ SELECT coalesce(
               string_to_array(NULLIF(current_setting('app.restaurant_ids', true), ''), ',')::uuid[],
               '{}'::uuid[]) $$;
        """
    )

    # --- Tables -----------------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        _ts(),
    )
    op.create_table(
        "restaurants",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100)),
        sa.Column("format", sa.String(100)),
        sa.Column("opened_on", sa.Date),
        _ts(),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        _ts(),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "role_assignments",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("restaurant_id", UUID, sa.ForeignKey("restaurants.id", ondelete="CASCADE")),
        _ts(),
        sa.CheckConstraint("role IN ('hq_admin', 'hq_analyst', 'restaurant_director')", name="role_valid"),
        sa.CheckConstraint(
            "(role = 'restaurant_director') = (restaurant_id IS NOT NULL)", name="scope_matches_role"
        ),
    )
    op.create_index("uq_role_assignments_one_per_user", "role_assignments", ["user_id"], unique=True)
    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity", sa.String(100)),
        sa.Column("entity_id", UUID),
        sa.Column("payload", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        _ts(),
    )

    # --- Row-level security -----------------------------------------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA app TO {app_role}")
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO {app_role}")
    rls.enable("tenants", "id = app.current_tenant_id()")
    rls.enable("restaurants", rls.restaurant_scope("id"))
    rls.enable("users", rls.own_user_scope("id"))
    rls.enable("role_assignments", rls.own_user_scope("user_id"))
    rls.enable("audit_log", rls.own_user_scope("user_id"))

    # Login happens before the tenant is known: a narrow lookup by email that bypasses RLS
    # (runs as the table owner) and returns only what authentication needs.
    op.execute(
        """
        CREATE FUNCTION app.auth_lookup_user(p_email text)
        RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text, is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS
        $$ SELECT u.id, u.tenant_id, u.password_hash::text, u.is_active
           FROM public.users u WHERE lower(u.email) = lower(p_email) $$;
        REVOKE ALL ON FUNCTION app.auth_lookup_user(text) FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app.auth_lookup_user(text) TO {app_role}")


def downgrade() -> None:
    for table in ("audit_log", "role_assignments", "users", "restaurants", "tenants"):
        op.drop_table(table)
    op.execute("DROP SCHEMA app CASCADE")
