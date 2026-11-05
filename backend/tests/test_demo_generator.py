"""The synthetic network is deterministic, valid and carries the planted anomalies (roadmap stage 2)."""

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime

import pytest

from app.demo.generator import COUNT_DAYS, ERP_NAMES, MENU, DemoNetwork, generate, load_plan

RECIPE = {m[0]: m[5] for m in MENU}


@pytest.fixture(scope="module")
def net() -> DemoNetwork:
    return generate(seed=42, restaurants=6)


def _rows(net: DemoNetwork, name: str) -> list[list[str]]:
    data = net.files[name]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251")
    return list(csv.reader(io.StringIO(text), delimiter=";"))[1:]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _day(s: str) -> date:
    return datetime.strptime(s, "%d.%m.%Y").date()


def overuse(net: DemoNetwork, code: str, product: str, start: date, end: date) -> float:
    """Unexplained usage over a period between two counts, as a share of usage by recipes."""
    counts = {_day(r[0]): _num(r[4]) for r in _rows(net, f"inventory_counts_{code}.csv") if r[1] == product}
    received = sum(
        _num(r[6]) * (0.001 if r[7] == "г" else 1)
        for r in _rows(net, f"receipts_{code}.csv")
        if (r[4] == product or r[5] == ERP_NAMES.get(product)) and start < _day(r[0]) <= end
    )
    written_off = sum(
        _num(r[3])
        for r in _rows(net, f"write_offs_{code}.csv")
        if r[1] == product and start < _day(r[0]) <= end
    )
    theory = sum(
        _num(r[3]) * RECIPE[r[1]].get(product, 0)
        for r in _rows(net, f"sales_{code}.csv")
        if start < _day(r[0]) <= end
    )
    return (counts[start] + received - written_off - counts[end]) / theory - 1


def test_same_seed_same_bytes() -> None:
    a, b = generate(seed=7, restaurants=2), generate(seed=7, restaurants=2)
    assert a.files == b.files
    assert generate(seed=8, restaurants=2).files != a.files


def test_files_and_plan(net: DemoNetwork) -> None:
    plan = load_plan(net)
    assert [p[0] for p in plan[:5]] == ["restaurants", "products", "suppliers", "menu_items", "recipes"]
    # 6 facts a restaurant (stage 6.5: + stock on a date, + the till's voids) + transfers of R05 and R06
    assert len(plan) == 5 + 6 * 6 + 2
    assert ("stock_balances", "R01", "stock_balances_R01.csv") in plan and (
        "voids",
        "R01",
        "voids_R01.csv",
    ) in plan
    assert ("transfers", "R05", "transfers_R05.csv") in plan
    assert ("transfers", "R06", "transfers_R06.csv") in plan
    assert "п/ф" in net.files["products.csv"].decode("utf-8-sig")  # the tomato sauce is semi-finished
    assert "sales_R01.xlsx" in net.files and "sales_R02.csv" in net.files
    truth = json.loads(net.files["anomalies.json"])
    ids = {a["id"] for a in truth["anomalies"]}
    assert {"r01-mozzarella-overuse", "r03-salmon-yield", "net-fries-recipe", "r02-beef-urgent-orders"} <= ids
    assert "r09-receipts-gap" not in ids  # R09 is not in a 6-restaurant network


def test_planted_overuse_is_recoverable_from_the_files(net: DemoNetwork) -> None:
    p2, p3 = (COUNT_DAYS[0], COUNT_DAYS[1]), (COUNT_DAYS[1], COUNT_DAYS[2])
    # A normal restaurant loses about its normal 2% of mozzarella; salmon in R03 runs ~6.8 points above that.
    assert overuse(net, "R02", "P01", *p3) == pytest.approx(0.02, abs=0.01)
    assert overuse(net, "R03", "P09", *p2) - overuse(net, "R04", "P09", *p2) == pytest.approx(
        0.068, abs=0.015
    )
    # Fries: the same overuse everywhere — the recipe is wrong, not the kitchens.
    for code in ("R02", "R03", "R05"):
        assert overuse(net, code, "P11", *p3) == pytest.approx(0.062 + 0.015, abs=0.012)


def test_planted_prices_and_habits(net: DemoNetwork) -> None:
    beef = defaultdict(list)
    for code in ("R02", "R03"):
        for r in _rows(net, f"receipts_{code}.csv"):
            if r[4] == "P08" and _day(r[0]) >= date(2026, 8, 1):
                beef[code].append(_num(r[8]))
    avg = {k: sum(v) / len(v) for k, v in beef.items()}
    assert avg["R02"] / avg["R03"] == pytest.approx(1.11, abs=0.02)

    def greens(code: str) -> float:
        return sum(_num(r[3]) for r in _rows(net, f"write_offs_{code}.csv") if r[1] == "P10")

    assert greens("R01") / 1.3 > 2.5 * greens("R03")  # per unit of size

    before_counts = sum(
        _num(r[3])
        for r in _rows(net, "write_offs_R01.csv")
        if any(0 < (c - _day(r[0])).days <= 2 for c in COUNT_DAYS)
    )
    total = sum(_num(r[3]) for r in _rows(net, "write_offs_R01.csv"))
    assert before_counts / total > 0.5


def test_names_from_another_system_are_suggested_correctly(net: DemoNetwork) -> None:
    """Quality gate for matching: the right product is the first suggestion for every 1С name."""
    from uuid import uuid4

    from app.demo.generator import PRODUCTS
    from app.imports.matching import suggest

    ids = {p[0]: uuid4() for p in PRODUCTS}
    options = [(ids[p[0]], p[1]) for p in PRODUCTS]
    assert len(net.name_matches) == 5
    for source, code in net.name_matches.items():
        best = suggest(source, options)
        assert best and best[0].id == ids[code], (source, best)


def test_the_stage_65_data_carry_their_planted_anomalies() -> None:
    """The till and the stock of the last weeks: R08's cashier voids after printing, R05's discounts, R06's
    cream outlives its shelf life — while the other restaurants' files stay as they were (own generator)."""
    import csv
    import io

    full = generate(seed=42)

    def rows(name: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(full.files[name].decode("utf-8-sig")), delimiter=";"))

    voids = rows("voids_R08.csv")
    by_cashier: dict[str, list[bool]] = {}
    for v in voids:
        by_cashier.setdefault(v["Кассир"], []).append(v["После пречека"] == "да")
    suspect = by_cashier.pop("таб. 103")
    others = [x for xs in by_cashier.values() for x in xs]
    assert sum(suspect) > 5 * max(1, sum(others))  # far more after printing
    sales = rows("sales_R05.csv")
    share = {
        c: sum(float(r["Скидка"].replace(",", ".")) for r in sales if r["Кассир"] == c)
        / sum(float(r["Выручка"].replace(",", ".")) for r in sales if r["Кассир"] == c)
        for c in {r["Кассир"] for r in sales}
    }
    assert share.pop("таб. 104") > 2 * max(share.values())
    stock = [r for r in rows("stock_balances_R06.csv") if r["Код товара"] == "P04"]
    assert len(stock) == 28 and max(float(r["Остаток"].replace(",", ".")) for r in stock) > 0
    ids = {a["id"] for a in json.loads(full.files["anomalies.json"])["anomalies"]}
    assert {"r06-cream-overstock", "r08-voids-after-print", "r05-cashier-discounts"} <= ids
