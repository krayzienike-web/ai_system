"""The audit log is append-only for the application (architecture review 27.10.2026, p. 7).

The application role could UPDATE and DELETE `audit_log` rows; with the tenant-wide scope it could erase the
network's log. Now it may only add and read entries.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

from app.core.config import get_settings

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {get_settings().app_db_role}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE, DELETE ON audit_log TO {get_settings().app_db_role}")
