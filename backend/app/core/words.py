"""Numbers in the words the screens use (the same rules as frontend/src/lib/format.ts).

Texts with conclusions are built on the server (ADR 0007); these helpers keep them readable: «15,2 тыс ₽»,
«3 находки», «на 2 пункта».
"""

from decimal import ROUND_HALF_UP, Decimal


def _num(value: Decimal, places: int) -> str:
    q = Decimal(1).scaleb(-places)
    text = f"{value.quantize(q, rounding=ROUND_HALF_UP):,}".replace(",", " ").replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def rub(value: Decimal | int) -> str:
    """38000 → «38 тыс ₽», 1250000 → «1,25 млн ₽», 900 → «900 ₽»."""
    v = Decimal(value)
    if abs(v) >= 1_000_000:
        return f"{_num(v / 1_000_000, 2)} млн ₽"
    if abs(v) >= 1_000:
        return f"{_num(v / 1_000, 1)} тыс ₽"
    return f"{_num(v, 0)} ₽"


def number(value: Decimal | int, places: int = 1) -> str:
    """1.54 → «1,5», 12345 → «12 345»."""
    return _num(Decimal(value), places)


def per_month(value: Decimal | int) -> str:
    return f"{rub(value)} в месяц"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(4, ("находка", "находки", "находок")) → «4 находки»."""
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        form = forms[0]
    elif 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n} {form}"


def percent(share: Decimal | None, places: int = 1) -> str:
    """0.2052 → «20,5%»."""
    return "—" if share is None else f"{_num(share * 100, places)}%"
