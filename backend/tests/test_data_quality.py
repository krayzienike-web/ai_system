"""M7, the data quality score of a restaurant, 0–100 (stage 6.5, docs/12; TC-ENG-35)."""

from datetime import date
from uuid import uuid4

from app.analytics import quality
from app.analytics.drafts import Draft
from app.analytics.facts import Facts

R1, R2, R3 = uuid4(), uuid4(), uuid4()


def _facts() -> Facts:
    f = Facts()
    f.restaurants = {R1: "R01", R2: "R02", R3: "R03"}
    return f


def _d(key: str, module: str, restaurant: object, confidence: str = "high", **evidence: object) -> Draft:
    return Draft(
        key=key,
        module=module,
        kind="problem",
        process="accounting",
        restaurant=restaurant,  # type: ignore[arg-type]
        title=key,
        headline="",
        effect_rub_month=None,
        effect_note=None,
        confidence=confidence,
        period_from=date(2026, 9, 21),
        period_to=date(2026, 10, 18),
        evidence=dict(evidence),
    )


def test_each_data_problem_takes_its_points_up_to_its_cap() -> None:
    drafts = [
        _d("M7:R01:receipts", "M7", R1, kind="gap"),
        _d("M7:R01:P01:negative", "M7", R1, kind="negative"),
        _d("M7:R01:P02:negative", "M7", R1, kind="negative"),
        _d("M7:R01:P03:negative", "M7", R1, kind="negative"),
        _d("M7:R01:P04:negative", "M7", R1, kind="negative"),  # the fourth: over the cap of 30
        _d("M7:R02:prices:P01", "M7", R2, kind="prices", lines=[{}] * 5),  # 5 × 5, capped at 20
        _d("M4:R02:paper", "M4", R2, kind="paper"),
        _d("M7:net:M12", "M7", None, kind="no_recipe", restaurants=["R01", "R02"]),
        _d("M1:R03:P01", "M1", R3),  # a finding about the money, not the data: no points
    ]
    scores = quality.score(drafts, _facts())
    assert scores[R1].score == 100 - 25 - 30 - 10
    assert {str(p["kind"]): p["points"] for p in scores[R1].parts} == {
        "gap": 25,
        "negative": 30,
        "no_recipe": 10,
    }
    assert scores[R2].score == 100 - 20 - 20 - 10
    assert scores[R3].score == 100 and scores[R3].parts == []
    assert scores[None].score == round((35 + 50 + 100) / 3)  # the network: the restaurants' average


def test_a_low_score_lowers_the_confidence_of_the_restaurants_findings_but_not_of_the_datas_own() -> None:
    gap = _d("M7:R01:receipts", "M7", R1, kind="gap")
    paper = _d("M4:R01:paper", "M4", R1, kind="paper")
    overdue = _d("M4:R01:overdue", "M4", R1, kind="overdue")
    loss = _d("M1:R01:P01", "M1", R1, confidence="high")
    elsewhere = _d("M1:R02:P01", "M1", R2, confidence="high")
    drafts = [gap, paper, overdue, loss, elsewhere]
    scores = quality.score(drafts, _facts())
    assert scores[R1].score == 40  # 100 − 25 − 20 − 15
    quality.apply(drafts, scores)
    assert loss.confidence == "medium" and loss.evidence["data_quality"] == 40
    assert paper.confidence == "medium"  # M4 is about the money too: its numbers stand on the same data
    assert gap.confidence == "high"  # the data's own finding says exactly what is wrong
    assert elsewhere.confidence == "high"  # R02: 100


def test_no_restaurants_no_scores() -> None:
    assert quality.score([], Facts()) == {}
