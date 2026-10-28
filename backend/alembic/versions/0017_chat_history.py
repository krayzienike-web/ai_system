"""The assistant's conversations (docs/08, «история диалогов в БД»).

A conversation is personal: its author reads and continues it, nobody else — not the HQ either (the strict
predicate below, not `own_user_scope`, which lets the HQ see everyone's rows).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core import rls_migrations as rls

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
AUTHOR_ONLY = f"{rls.TENANT} AND user_id = app.current_user_id()"


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", UUID, sa.ForeignKey("findings.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_chat_threads_tenant_user_updated", "chat_threads", ["tenant_id", "user_id", "updated_at"]
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("thread_id", UUID, sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
    )
    op.create_index("ix_chat_messages_thread_seq", "chat_messages", ["thread_id", "seq"], unique=True)
    rls.enable("chat_threads", AUTHOR_ONLY)
    rls.enable("chat_messages", AUTHOR_ONLY)


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
