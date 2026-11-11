"""The pilot's configuration (stage 8, step 7; pre-pilot review 10.11.2026, pp. 4, 5, 18):
- `auth_sessions`: a refresh token per sign-in, stored as its hash; refreshing rotates it, signing out or
  a new password revokes it. Only the user's own rows are visible (RLS); the token is found before any
  tenant is known through a narrow SECURITY DEFINER function, as login finds the user;
- `users.must_change_password`: a password handed out by the operator is changed at the first sign-in;
- `import_batches.raw_deleted_at`: the source file is deleted after its retention period, the batch stays.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls
from app.core.config import get_settings

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    app_role = get_settings().app_db_role
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.add_column("import_batches", sa.Column("raw_deleted_at", sa.DateTime(timezone=True)))

    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        # One sign-in: every rotated token of it shares the family, a reused old token revokes the family.
        sa.Column("family_id", UUID, nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    rls.enable("auth_sessions", f"{rls.TENANT} AND user_id = app.current_user_id()")
    op.execute(
        """
        CREATE FUNCTION app.auth_lookup_session(p_hash text)
        RETURNS TABLE (session_id uuid, user_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS
        $$ SELECT s.id, s.user_id, s.tenant_id FROM public.auth_sessions s WHERE s.token_hash = p_hash $$;
        REVOKE ALL ON FUNCTION app.auth_lookup_session(text) FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app.auth_lookup_session(text) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.auth_lookup_session(text)")
    op.drop_table("auth_sessions")
    op.drop_column("import_batches", "raw_deleted_at")
    op.drop_column("users", "must_change_password")
