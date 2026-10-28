"""Every number of the model's answer must come from the tools' results (CLAUDE.md, principle 1; docs/03,
«Защита от галлюцинаций»).

Numbers are compared as values, not as text: «12 400 ₽», «12400» and «12 400,00» are one number, «31,2%» and
«31.2» too; a date («30.09.2026») is one value, a minus sign counts. Only plain counting numbers of a text
(«3 шага», a list number) — integers up to `SMALL` with no unit after them — need no source: «4%», «2 п.п.»,
«в 3 раза» are figures and are always checked (code review 28.10.2026, p. 1). Multipliers in words («вдвое»)
cannot be checked, so they are reported too. Ids in the sources are not numbers and allow nothing.
"""

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

SMALL = 10
SPACE = "[   ]"
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?![\d.])")
NUMBER = re.compile(
    rf"(?<![\w.,])(?P<sign>[-−])?(?P<num>\d{{1,3}}(?:{SPACE}\d{{3}})+(?:[.,]\d+)?(?!\d)|\d+(?:[.,]\d+)?)"
)
# A figure, not a count: a unit or a scale right after the number.
UNIT = re.compile(
    rf"^{SPACE}*(?:%|п\.?\s?п|₽|руб|р\.|раз|тыс|млн|млрд|дн|ден|недел|месяц|час|кг|г\b|л\b|шт|порц)", re.I
)
WORDS = re.compile(
    r"(?<!\w)(вдвое|втрое|вчетверо|впятеро|вдесятеро|в разы|в полтора раза|половин\w*|треть\w*)", re.I
)


def _values(text: str) -> list[tuple[str, bool]]:
    """(value, is a figure) for every number of the text, in order; dates as `d:YYYY-MM-DD`."""
    out: list[tuple[int, str, bool]] = []

    def date(m: re.Match[str]) -> str:
        out.append((m.start(), f"d:{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}", True))
        return " " * len(m[0])

    text = DATE.sub(date, text)
    for m in NUMBER.finditer(text):
        clean = re.sub(SPACE, "", m["num"]).replace(",", ".")
        try:
            value = Decimal(clean).normalize()
        except InvalidOperation:  # pragma: no cover - the pattern only matches numbers
            continue
        if m["sign"]:
            value = -value
        out.append((m.start(), format(value, "f"), bool(UNIT.match(text[m.end() :]))))
    return [(v, f) for _, v, f in sorted(out)]


def numbers(text: str) -> set[str]:
    return {v for v, _ in _values(text)}


def _source_text(source: Any) -> str:
    text = source if isinstance(source, str) else json.dumps(source, ensure_ascii=False, default=str)
    return UUID.sub(" ", text)


def unsupported(answer: str, sources: Iterable[Any]) -> list[str]:
    """Figures of the answer found in none of the sources (tool results), in order of appearance."""
    allowed: set[str] = set()
    for source in sources:
        allowed |= numbers(_source_text(source))
    out: list[str] = []
    for value, figure in _values(answer):
        if value in allowed or value in out:
            continue
        if not figure and not value.startswith(("d:", "-")) and "." not in value and int(value) <= SMALL:
            continue  # a count: «3 шага», «1.» of a list
        out.append(value)
    out += [w.lower() for w in WORDS.findall(answer)]
    return out
