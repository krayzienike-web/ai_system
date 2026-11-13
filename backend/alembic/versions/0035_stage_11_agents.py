"""Three more agents (stage 11, ADR 0010): negotiating with a supplier for the network, updating a recipe
card the network overspends, following a check of a change. All three write to the HQ, about the network.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As of this revision: a later migration that adds an agent changes the constraint itself.
BEFORE = (
    "inventory_prep",
    "task_due",
    "task_stuck",
    "data_check",
    "shortage_story",
    "supplier_claim",
    "transfer",
    "hq_agenda",
)
AGENTS = (*BEFORE, "supplier_deal", "recipe_update", "check_watch")


def _agents(names: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE agent_notes DROP CONSTRAINT ck_agent_notes_agent_valid")
    op.execute(f"ALTER TABLE agent_notes ADD CONSTRAINT ck_agent_notes_agent_valid CHECK (agent IN {names})")


def upgrade() -> None:
    _agents(AGENTS)


def downgrade() -> None:
    op.execute("DELETE FROM agent_notes WHERE agent IN ('supplier_deal', 'recipe_update', 'check_watch')")
    _agents(BEFORE)
