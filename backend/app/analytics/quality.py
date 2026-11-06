"""M7. The data quality score of a restaurant, 0–100 (stage 6.5; docs/12, «Оценка качества данных»).

100 less a penalty for each data problem the engine found in this restaurant's data on this run: the score
says how far the other findings of the restaurant can be trusted. Below `M7_DQ_LOW` the restaurant's findings
(other than the data's own) drop one level of confidence: their numbers stand on data with known holes.

The network's score is the average of its restaurants'.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.analytics.drafts import Draft
from app.analytics.facts import Facts
from app.analytics.params import DEFAULT, EngineParams

# (label, points off, cap for the kind) — the same problem in several products counts up to the cap
PENALTIES: dict[str, tuple[str, int, int]] = {
    "gap": ("Выгрузка не загружена", 25, 50),
    "paper": ("Инвентаризации «на бумаге»", 20, 20),
    "overdue": ("Инвентаризация просрочена", 15, 15),
    "partial": ("Инвентаризация без части товаров", 10, 10),
    "negative": ("Остаток по документам в минусе", 10, 30),
    "prices": ("Ошибочные цены в накладных", 5, 20),  # per line
    "no_recipe": ("Продается блюдо без техкарты", 10, 10),
}
DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


@dataclass
class Quality:
    score: int = 100
    parts: list[dict[str, object]] = field(default_factory=list)  # {kind, label, points, finding}


def _hits(d: Draft, facts: Facts) -> list[tuple[UUID, str, int]]:
    """(restaurant, kind, how many) a data finding costs."""
    kind = str(d.evidence.get("kind", ""))
    if kind not in PENALTIES:
        return []
    if kind == "no_recipe":
        codes = set(d.evidence.get("restaurants") or [])
        return [(r, kind, 1) for r, code in facts.restaurants.items() if code in codes]
    if d.restaurant is None:
        return []
    if kind == "prices":
        return [(d.restaurant, kind, len(d.evidence.get("lines") or []))]
    return [(d.restaurant, kind, 1)]


def score(drafts: list[Draft], facts: Facts) -> dict[UUID | None, Quality]:
    found: dict[UUID, dict[str, list[tuple[int, str]]]] = {r: {} for r in facts.restaurants}
    for d in drafts:
        for restaurant, kind, n in _hits(d, facts):
            found.setdefault(restaurant, {}).setdefault(kind, []).append((n, d.key))
    out: dict[UUID | None, Quality] = {}
    for restaurant, kinds in found.items():
        q = Quality()
        for kind, hits in sorted(kinds.items()):
            label, each, cap = PENALTIES[kind]
            points = min(sum(n for n, _ in hits) * each, cap)
            q.parts.append({"kind": kind, "label": label, "points": points, "findings": [k for _, k in hits]})
            q.score -= points
        q.score = max(q.score, 0)
        out[restaurant] = q
    if out:
        mean = Decimal(sum(q.score for q in out.values())) / len(out)
        out[None] = Quality(score=int(mean.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    return out


def apply(drafts: list[Draft], scores: dict[UUID | None, Quality], cfg: EngineParams = DEFAULT) -> None:
    """A restaurant with a low score: its findings lose one level of confidence — but not the data problems
    themselves (the kinds that take the points: M7, M4 «на бумаге», «просрочена»), they say exactly what is
    wrong. The card says why (code review of stage 6.5, p. 13). Runs after the views are built."""
    for d in drafts:
        q = scores.get(d.restaurant) if d.restaurant is not None else None
        if q is None or q.score >= cfg.M7_DQ_LOW or d.module == "M7" or d.evidence.get("kind") in PENALTIES:
            continue
        d.confidence = DOWNGRADE.get(d.confidence, d.confidence)
        d.evidence = {**d.evidence, "data_quality": q.score}
        if d.view is not None:
            why = f"уверенность снижена: качество данных ресторана {q.score} из 100"
            note = d.view.get("confidence_note")
            d.view = {**d.view, "confidence_note": f"{note}; {why}" if note else why.capitalize()}
