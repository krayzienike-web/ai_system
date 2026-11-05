"""M8. The till: removals after the check was printed and discounts, by cashier (stage 6.5; docs/12, M8).

Over the last `M8_WINDOW_DAYS` of the till's data:
- **removals after printing** — a cashier whose dishes removed after the check was printed (r_keeper's
  «Удаления и отмены») add up to many times the typical cashier's of the network: the guest paid, the dish
  left the bill — a risk of abuse at the till;
- **discounts** — a cashier whose discounts take a far larger share of their sales than the typical
  cashier's; when the sales carry no cashier, the restaurant against the network.

The effect is what stands above the typical: the removals over the median cashier's, the discounts over the
median share, per month. Cashiers are compared as the till names them (a code: docs/09, personal data).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from uuid import UUID

from app.analytics.drafts import Draft, dmy, pct, per_month, rub
from app.analytics.facts import Facts
from app.analytics.params import DEFAULT, EngineParams

ACTIONS_VOIDS = [
    "Разобрать удаления после пречека с кассиром: какие чеки, кто подтверждал",
    "Включить подтверждение менеджера на удаление после печати пречека",
]
ACTIONS_DISCOUNTS = [
    "Проверить, по каким основаниям даны скидки: карты гостей, акции, комплименты",
    "Ограничить ручные скидки кассира и включить подтверждение менеджера",
]


@dataclass
class Cashier:
    restaurant: UUID
    name: str | None
    removed_after_print: Decimal = Decimal(0)
    removals_after_print: int = 0
    gross: Decimal = Decimal(0)  # sales before discounts
    discount: Decimal = Decimal(0)

    @property
    def share(self) -> Decimal | None:
        return self.discount / self.gross if self.gross > 0 else None


def window(facts: Facts, cfg: EngineParams = DEFAULT) -> tuple[date, date] | None:
    days = [v.day for v in facts.voids] + [s.day for s in facts.sales]
    if not days:
        return None
    end = max(days)
    return end - timedelta(days=cfg.M8_WINDOW_DAYS - 1), end


def cashiers(facts: Facts, start: date, end: date) -> dict[tuple[UUID, str | None], Cashier]:
    out: dict[tuple[UUID, str | None], Cashier] = {}

    def of(restaurant: UUID, name: str | None) -> Cashier:
        return out.setdefault((restaurant, name), Cashier(restaurant, name))

    for v in facts.voids:
        if start <= v.day <= end and v.after_print:
            c = of(v.restaurant, v.cashier)
            c.removed_after_print += v.amount
            c.removals_after_print += 1
    for s in facts.sales:
        if start <= s.day <= end:
            c = of(s.restaurant, s.cashier)
            c.gross += s.revenue + s.discount
            c.discount += s.discount
    return out


def detect(facts: Facts, cfg: EngineParams = DEFAULT) -> list[Draft]:
    span = window(facts, cfg)
    if span is None:
        return []
    start, end = span
    rows = cashiers(facts, start, end)
    named = [c for c in rows.values() if c.name is not None]
    drafts = _removals(facts, named, start, end, cfg) + _discounts(facts, named, start, end, cfg)
    flagged = {d.restaurant for d in drafts if d.evidence["kind"] == "discounts"}
    return drafts + _restaurant_discounts(facts, list(rows.values()), flagged, start, end, cfg)


def _removals(facts: Facts, named: list[Cashier], start: date, end: date, cfg: EngineParams) -> list[Draft]:
    with_sales = [c for c in named if c.gross > 0 or c.removals_after_print]
    if len(with_sales) < 3:
        return []
    typical = Decimal(median([c.removed_after_print for c in with_sales]))
    out = []
    for c in with_sales:
        if c.removals_after_print < cfg.M8_VOIDS_MIN_COUNT:
            continue
        if c.removed_after_print < cfg.M8_VOIDS_TIMES * max(typical, Decimal(1)):
            continue
        effect = per_month(c.removed_after_print - typical, start, end)
        if effect < cfg.M8_MATERIALITY_RUB_MONTH:
            continue
        code = facts.restaurants[c.restaurant]
        out.append(
            Draft(
                key=f"M8:{code}:voids:{c.name}",
                module="M8",
                kind="problem",
                process="accounting",
                restaurant=c.restaurant,
                title=f"Удаления после пречека: кассир {c.name}",
                headline=(
                    f"За {dmy(start)}–{dmy(end)} кассир {c.name} удалил после печати пречека "
                    f"{c.removals_after_print} позиций на {rub(c.removed_after_print)} — "
                    f"у обычного кассира сети {rub(typical)}. Сверх обычного ≈ {rub(effect)} в месяц: "
                    "деньги гостя могли не дойти до кассы"
                ),
                effect_rub_month=effect,
                effect_note="риск: удаления после пречека сверх обычного",
                confidence="medium",
                period_from=start,
                period_to=end,
                actions=list(ACTIONS_VOIDS),
                evidence={
                    "kind": "voids",
                    "cashier": c.name,
                    "count": c.removals_after_print,
                    "amount": str(c.removed_after_print.quantize(Decimal("0.01"))),
                    "network_median": str(typical.quantize(Decimal("0.01"))),
                    "cashiers": len(with_sales),
                },
            )
        )
    return out


def _discounts(facts: Facts, named: list[Cashier], start: date, end: date, cfg: EngineParams) -> list[Draft]:
    selling = [c for c in named if c.gross > 0 and c.share is not None]
    if len(selling) < 3:
        return []
    typical = Decimal(median([c.share for c in selling if c.share is not None]))
    out = []
    for c in selling:
        assert c.share is not None
        if c.share < cfg.M8_DISCOUNT_TIMES * typical or c.share - typical < cfg.M8_DISCOUNT_EXCESS:
            continue
        effect = per_month(c.gross * (c.share - typical), start, end)
        if effect < cfg.M8_MATERIALITY_RUB_MONTH:
            continue
        code = facts.restaurants[c.restaurant]
        out.append(_discount_draft(f"M8:{code}:discounts:{c.name}", c, typical, effect, start, end, code))
    return out


def _restaurant_discounts(
    facts: Facts, rows: list[Cashier], flagged: set[UUID | None], start: date, end: date, cfg: EngineParams
) -> list[Draft]:
    """When the sales carry no cashier: the restaurant's share of discounts against the network's."""
    by_restaurant: dict[UUID, Cashier] = defaultdict(lambda: Cashier(UUID(int=0), None))
    for c in rows:
        r = by_restaurant[c.restaurant]
        r.restaurant, r.gross, r.discount = c.restaurant, r.gross + c.gross, r.discount + c.discount
    places = [r for r in by_restaurant.values() if r.share is not None]
    if len(places) < 3:
        return []
    out = []
    for r in places:
        others = [o.share for o in places if o.restaurant != r.restaurant and o.share is not None]
        typical = Decimal(median(others))
        assert r.share is not None
        has_cashiers = any(c.name is not None for c in rows if c.restaurant == r.restaurant)
        if r.restaurant in flagged or has_cashiers:
            continue  # the cashier's finding says it better
        if r.share < cfg.M8_DISCOUNT_TIMES * typical or r.share - typical < cfg.M8_DISCOUNT_EXCESS:
            continue
        effect = per_month(r.gross * (r.share - typical), start, end)
        if effect < cfg.M8_MATERIALITY_RUB_MONTH:
            continue
        code = facts.restaurants[r.restaurant]
        out.append(_discount_draft(f"M8:{code}:discounts", r, typical, effect, start, end, code))
    return out


def _discount_draft(
    key: str, c: Cashier, typical: Decimal, effect: Decimal, start: date, end: date, code: str
) -> Draft:
    assert c.share is not None
    who = f"кассир {c.name}" if c.name else "ресторан"
    return Draft(
        key=key,
        module="M8",
        kind="problem",
        process="accounting",
        restaurant=c.restaurant,
        title=f"Скидки выше обычного: {who}" if c.name else f"Скидки выше сети: {code}",
        headline=(
            f"За {dmy(start)}–{dmy(end)} скидки — {pct(c.share)} продаж ({who}), "
            f"обычно по сети {pct(typical)}. "
            f"Сверх обычного ≈ {rub(effect)} в месяц"
        ),
        effect_rub_month=effect,
        effect_note=None,
        confidence="medium",
        period_from=start,
        period_to=end,
        actions=list(ACTIONS_DISCOUNTS),
        evidence={
            "kind": "discounts",
            "cashier": c.name,
            "share": str(c.share.quantize(Decimal("0.0001"))),
            "network_share": str(typical.quantize(Decimal("0.0001"))),
            "gross": str(c.gross.quantize(Decimal("0.01"))),
            "discount": str(c.discount.quantize(Decimal("0.01"))),
        },
    )
