"""Every number of the model's answer must come from the tools' results (CLAUDE.md, principle 1; docs/03,
«Защита от галлюцинаций»).

Numbers are compared as values, not as text: «12 400 ₽», «12400» and «12 400,00» are one number, «31,2%» and
«31.2» too. Allowed: what the tool results and the question contain, plus small counting words of a text
(«3 шага», list numbers) — integers up to `SMALL`. Anything else is reported, and the chat asks the model to
correct the answer or falls back to the answer by rules.
"""

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

SMALL = 10
# 12 400 / 12 400,50 / 31.2 / 0,5 — groups of three digits joined by a space or a no-break space.
NUMBER = re.compile(
    r"(?<![\w.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w])\d+(?:[.,]\d+)?"
)


def numbers(text: str) -> set[Decimal]:
    found = set()
    for raw in NUMBER.findall(text):
        clean = re.sub(r"[ \u00a0\u202f]", "", raw).replace(",", ".")
        try:
            found.add(Decimal(clean).normalize())
        except InvalidOperation:  # pragma: no cover - the pattern only matches numbers
            continue
    return found


def unsupported(answer: str, sources: Iterable[Any]) -> list[str]:
    """Numbers of the answer found in none of the sources (tool results, the question), in order."""
    allowed: set[Decimal] = set()
    for source in sources:
        allowed |= numbers(
            source if isinstance(source, str) else json.dumps(source, ensure_ascii=False, default=str)
        )
    out = []
    for n in sorted(numbers(answer)):
        if n in allowed or (n == n.to_integral_value() and 0 <= n <= SMALL):
            continue
        out.append(format(n, "f"))
    return out
