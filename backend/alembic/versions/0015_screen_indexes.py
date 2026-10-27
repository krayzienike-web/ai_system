"""Indexes for what the screens ask on every visit (architecture review 27.10.2026, p. 18).

`/overview/context` asks the network's last day of sales and its stock count days; the facts were indexed by
restaurant and day only. Findings are listed by restaurant and status, tasks are counted by status and due
date.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACTS = ("sales", "receipts", "write_offs", "inventory_counts", "transfers")


def upgrade() -> None:
    for table in FACTS:
        op.create_index(f"ix_{table}_tenant_day", table, ["tenant_id", "day"])
    op.create_index(
        "ix_findings_tenant_restaurant_status", "findings", ["tenant_id", "restaurant_id", "status"]
    )
    op.create_index("ix_tasks_tenant_status_due", "tasks", ["tenant_id", "status", "due_on"])


def downgrade() -> None:
    op.drop_index("ix_tasks_tenant_status_due", table_name="tasks")
    op.drop_index("ix_findings_tenant_restaurant_status", table_name="findings")
    for table in FACTS:
        op.drop_index(f"ix_{table}_tenant_day", table_name=table)
