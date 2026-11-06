"""How much each finding counts for in a sum (docs/12, «Связанные находки»): one cause, one sum.

The findings of a story count the same money twice (spoiled cream is both the overstock and the write-offs),
so the story counts once — as its largest finding, which also gives the story its process. A `supplier`
story is the exception: overuse (extra quantity × price) and an overpayment (extra price × all bought) are
different money, they add up.

Every total on the screens, in the digest, the trend and the report goes through `counted`, so they agree.
"""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from app.insights.models import Finding

ZERO = Decimal(0)
ADDING = ("supplier:",)  # stories whose findings are different money


def counted(findings: Iterable[Finding]) -> dict[UUID, Decimal]:
    """Finding id → the money it adds to a sum of these findings."""
    out: dict[UUID, Decimal] = {}
    stories: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.story_key and not f.story_key.startswith(ADDING):
            stories[f.story_key].append(f)
        else:
            out[f.id] = f.effect_rub_month or ZERO
    for members in stories.values():
        largest = max(members, key=lambda f: (f.effect_rub_month or ZERO, str(f.id)))
        for f in members:
            out[f.id] = (f.effect_rub_month or ZERO) if f is largest else ZERO
    return out


def story_sum(key: str, effects: list[Decimal | None]) -> Decimal | None:
    """The sum a story's card shows: its largest finding's, or all of them for an adding story."""
    known = [e for e in effects if e is not None]
    if not known:
        return None
    return sum(known, ZERO) if key.startswith(ADDING) else max(known)
