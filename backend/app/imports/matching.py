"""Matching names across systems: «Моцарелла фиор ди латте 45%» in 1С is «Сыр Моцарелла» in iiko.

Order (docs/04-data-import.md): exact code → exact name after normalisation → a remembered alias →
suggestions for a person to confirm once. A suggestion is never applied silently: a wrong match would
quietly distort every number built on it. Pure functions, unit-tested.
"""

import re
from dataclasses import dataclass
from uuid import UUID

# Words that carry no identity: "свежий", "охл.", units and packaging.
NOISE = {
    "свеж",
    "свежий",
    "свежая",
    "свежие",
    "охл",
    "охлажденный",
    "охлажденное",
    "зам",
    "замороженный",
    "кг",
    "г",
    "гр",
    "л",
    "мл",
    "шт",
    "уп",
    "упак",
    "вес",
    "весовой",
}


def normalize(text: str) -> str:
    """Case, «ё», punctuation and spaces do not make two names different."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if t not in NOISE and not t.isdigit()}


def _trigrams(text: str) -> set[str]:
    s = f"  {' '.join(sorted(_tokens(text)))} "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _word_overlap(a: set[str], b: set[str]) -> float:
    """Shared words, abbreviations included («оливк.» ~ «оливковое»): the average of how much of the
    shorter name and how much of the longer one they cover — extra words like «фиор ди латте» cost less."""
    if not a or not b:
        return 0.0
    hits = sum(1 for x in a if any(y.startswith(x) or x.startswith(y) for y in b if min(len(x), len(y)) >= 4))
    return (hits / min(len(a), len(b)) + hits / max(len(a), len(b))) / 2


def similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    trigram = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return round(max(trigram, _word_overlap(_tokens(a), _tokens(b))), 3)


@dataclass(frozen=True)
class Candidate:
    id: UUID
    name: str
    score: float


def suggest(
    name: str, options: list[tuple[UUID, str]], *, limit: int = 3, threshold: float = 0.3
) -> list[Candidate]:
    scored = [Candidate(i, n, similarity(name, n)) for i, n in options]
    good = [c for c in scored if c.score >= threshold]
    return sorted(good, key=lambda c: (-c.score, c.name))[:limit]
