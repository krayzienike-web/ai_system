"""Two more agents (stage 12, ADR 0010): the result of a stock count (to the director, and a summary of the
network to the HQ) and menu prices after purchases grew (to the HQ).

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
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
    "supplier_deal",
    "recipe_update",
    "check_watch",
)
AGENTS = (*BEFORE, "count_result", "menu_price")


def _agents(names: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE agent_notes DROP CONSTRAINT ck_agent_notes_agent_valid")
    op.execute(f"ALTER TABLE agent_notes ADD CONSTRAINT ck_agent_notes_agent_valid CHECK (agent IN {names})")


def upgrade() -> None:
    _agents(AGENTS)


def downgrade() -> None:
    op.execute("DELETE FROM agent_notes WHERE agent IN ('count_result', 'menu_price')")
    _agents(BEFORE)
