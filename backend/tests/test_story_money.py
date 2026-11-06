"""A story's money counts once on every screen (code review of stage 6.5, p. 1 and 6; docs/12; TC-ENG-36)."""

from decimal import Decimal
from uuid import uuid4

from app.insights.models import Finding
from app.insights.money import counted, story_sum

D = Decimal


def _f(effect: int | None, story: str | None = None, process: str = "planning") -> Finding:
    return Finding(
        id=uuid4(), effect_rub_month=None if effect is None else D(effect), story_key=story, process=process
    )


def test_a_story_counts_once_as_its_largest_finding_which_also_gives_its_process() -> None:
    over = _f(21253, "supply:R06:P04", "planning")
    waste = _f(21220, "supply:R06:P04", "writeoffs")
    alone = _f(5000)
    money = counted([over, waste, alone])
    assert money[over.id] == D(21253) and money[waste.id] == 0 and money[alone.id] == D(5000)
    assert sum(money.values()) == D(26253)  # not 47 473
    assert story_sum("supply:R06:P04", [D(21253), D(21220)]) == D(21253)


def test_a_supplier_story_adds_up_its_findings_they_count_different_money() -> None:
    overuse = _f(30000, "supplier:R02:P08", "production")
    overpay = _f(20000, "supplier:R02:P08", "purchasing")
    money = counted([overuse, overpay])
    assert money[overuse.id] == D(30000) and money[overpay.id] == D(20000)
    assert story_sum("supplier:R02:P08", [D(30000), D(20000)]) == D(50000)


def test_findings_without_a_sum_count_nothing() -> None:
    a, b = _f(None, "receipts:R10:P01"), _f(None, "receipts:R10:P01")
    assert counted([a, b]) == {a.id: 0, b.id: 0}
    assert story_sum("receipts:R10:P01", [None, None]) is None
