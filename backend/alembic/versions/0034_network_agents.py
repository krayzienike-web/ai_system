"""Four more agents (stage 10, ADR 0010): the shortage story, the supplier request, the transfer, the HQ's
weekly agenda. A note to the HQ may be about the whole network: no restaurant. A director never sees it —
the row-level security of migration 0032 needs a restaurant of theirs and a note to the director.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As of this revision: a later migration that adds an agent changes the constraint itself.
BEFORE = ("inventory_prep", "task_due", "task_stuck", "data_check")
AGENTS = (*BEFORE, "shortage_story", "supplier_claim", "transfer", "hq_agenda")


def _agents(names: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE agent_notes DROP CONSTRAINT ck_agent_notes_agent_valid")
    op.execute(f"ALTER TABLE agent_notes ADD CONSTRAINT ck_agent_notes_agent_valid CHECK (agent IN {names})")


def upgrade() -> None:
    _agents(AGENTS)
    op.execute("ALTER TABLE agent_notes ALTER COLUMN restaurant_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE agent_notes ADD CONSTRAINT ck_agent_notes_network_notes_to_hq "
        "CHECK (restaurant_id IS NOT NULL OR audience = 'hq')"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM agent_notes WHERE restaurant_id IS NULL "
        "OR agent IN ('shortage_story', 'supplier_claim', 'transfer', 'hq_agenda')"
    )
    op.execute("ALTER TABLE agent_notes DROP CONSTRAINT ck_agent_notes_network_notes_to_hq")
    op.execute("ALTER TABLE agent_notes ALTER COLUMN restaurant_id SET NOT NULL")
    _agents(BEFORE)
