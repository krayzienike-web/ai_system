"""Engine parameters: thresholds and windows of the detectors (docs/12-analytics-engine.md, «Параметры»).

The values below are the defaults. A network's HQ admin may set its own in «Нормы и настройки» → «Параметры
движка» (`norm_settings.engine_params`); every run and every verification reads them with `load(session)`.
The network's norms (food-cost target, loss allowances) live in app/norms.
"""

from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class EngineParams:
    # Shared
    NETWORK_Z_MIN_RESTAURANTS: int = 8  # below this the network is too small for a z-score (pilot of 3)
    # A checked finding goes back to the check when its effect changes by more than this share
    REVIEW_RECHECK_CHANGE: Decimal = Decimal("0.25")
    # M1 — recipe execution
    M1_MATERIALITY_RUB_MONTH: Decimal = Decimal(3000)  # smaller losses are not worth a director's attention
    M1_Z: Decimal = Decimal(2)  # how far from the network a restaurant must be (robust z-score)
    M1_Z_FLOOR: Decimal = Decimal("0.005")  # 0.5 p.p.: the smallest spread the z-score assumes
    M1_NET_SHARE: Decimal = Decimal("0.75")  # share of restaurants over the allowance → the recipe is wrong
    M1_NET_EXCESS: Decimal = Decimal("0.02")  # … and the median is at least 2 p.p. over the allowance
    M1_MIN_THEORY_DAYS: int = 14  # a period between counts shorter than this is not judged
    # Restaurants count on their own days: periods of others that ended this close are compared with it
    M1_NET_ALIGN_DAYS: int = 31
    M1_UNDER: Decimal = Decimal("0.05")  # 5 %: used less than the recipes say → under-portioning risk
    # M2 — food cost of dishes
    M2_WINDOW_DAYS: int = 28  # current ingredient prices: the network's purchases over the last 4 weeks
    M2_COMPARE_DAYS: int = 91  # «before»: the same window a quarter earlier
    M2_KEEP: Decimal = Decimal("0.5")  # conservative: half of the extra margin survives guests ordering less
    M2_MATERIALITY_RUB_MONTH: Decimal = Decimal(3000)
    M2_PRICE_STEP: Decimal = Decimal(10)  # suggested menu prices are rounded up to 10 ₽
    # M3 — purchase prices
    M3_WINDOW_DAYS: int = 56  # the last 8 weeks of purchases are compared
    M3_MIN_RECEIPTS: int = 2  # fewer purchases of a product in the window: no conclusion
    M3_OVERPAY: Decimal = Decimal("0.05")  # 5 % above the typical price of the network
    M3_MATERIALITY_RUB_MONTH: Decimal = Decimal(3000)
    M3_Z: Decimal = Decimal(2)
    M3_Z_FLOOR: Decimal = Decimal("0.01")  # 1 %: the smallest price spread the z-score assumes
    M3_CONTRACT_TOLERANCE: Decimal = Decimal("0.01")  # rounding in invoices: up to 1 % over the contract
    M3_NET_WINDOW_DAYS: int = 28  # network-wide growth: the last 4 weeks …
    M3_NET_COMPARE_DAYS: int = 91  # … against the same 4 weeks a quarter earlier
    M3_NET_GROWTH: Decimal = Decimal("0.10")  # 10 % more for the whole network
    # M4 — stock counts
    M4_PRE_DAYS: int = 2  # write-offs dated this many days before a count …
    M4_PRE_SHARE: Decimal = Decimal("0.5")  # … holding at least half of them …
    M4_PRE_TIMES: Decimal = Decimal(3)  # … and 3 times what evenly spread write-offs would give
    M4_SORT_SHARE: Decimal = Decimal("0.05")  # a surplus of at least 5 % of the books at the last count …
    M4_SORT_MATCH: Decimal = Decimal("0.3")  # … and a shortage of a same-category product within 30 % of it
    # M5 — write-offs
    M5_WINDOW_DAYS: int = 28
    M5_TIMES: Decimal = Decimal(2)  # written off / bought at least twice the network's median …
    M5_EXCESS: Decimal = Decimal("0.03")  # … and at least 3 p.p. more
    M5_WEEKDAY_SHARE: Decimal = Decimal("0.5")  # two neighbouring weekdays hold half of the write-offs …
    M5_WEEKDAY_WEEKS: int = 3  # … in at least 3 weeks of the window
    M5_MATERIALITY_RUB_MONTH: Decimal = Decimal(3000)
    # A weekday pattern is a sure and cheap fix (order by day), so smaller sums are worth showing
    M5_WEEKDAY_MATERIALITY_RUB_MONTH: Decimal = Decimal(1000)
    # M7 — data quality
    M7_WINDOW_DAYS: int = 28  # a dish sold without a recipe within the last 4 weeks
    M7_GAP_DAYS: int = 5  # an export missing for this many days, while other restaurants have them …
    M7_GAP_TIMES: Decimal = Decimal(2)  # … and longer than twice the restaurant's usual pause between days
    M7_HISTORY_DAYS: int = 56  # the usual pause: over the last 8 weeks of the restaurant's data


DEFAULT = EngineParams()


@dataclass(frozen=True)
class ParamDef:
    """How a parameter is shown and edited: people see 75 %, the engine uses 0.75 (`scale` = 100)."""

    key: str
    module: str  # ALL | M1 | M2 | M3
    title: str
    unit: str
    meaning: str
    low: Decimal  # in the units people see
    high: Decimal
    scale: Decimal = Decimal(1)

    def shown(self, value: Decimal | int) -> Decimal:
        v = Decimal(value) * self.scale
        return v.quantize(Decimal(1)) if v == v.to_integral_value() else v.normalize()

    def stored(self, shown: Decimal) -> Decimal | int:
        value = Decimal(shown) / self.scale
        return int(value) if isinstance(getattr(DEFAULT, self.key), int) else value


D = Decimal
PCT = D(100)
DEFS: tuple[ParamDef, ...] = (
    ParamDef(
        "NETWORK_Z_MIN_RESTAURANTS",
        "ALL",
        "Сравнение с сетью (z-score) включается с",
        "ресторанов",
        "меньше — сравниваем только с допусками и нормами",
        D(3),
        D(50),
    ),
    ParamDef(
        "REVIEW_RECHECK_CHANGE",
        "ALL",
        "Проверенная находка возвращается на проверку, если эффект изменился больше чем на",
        "%",
        "после новых данных директор не увидит без проверки сумму, которую никто не подтверждал",
        D(5),
        D(200),
        PCT,
    ),
    ParamDef(
        "M1_MATERIALITY_RUB_MONTH",
        "M1",
        "Ниже какой суммы потерь не показываем",
        "₽ в месяц",
        "по одному товару в ресторане",
        D(0),
        D(100000),
    ),
    ParamDef(
        "M1_Z",
        "M1",
        "Насколько ресторан должен выделяться (z-score)",
        "",
        "больше — реже находки, только явные случаи",
        D(1),
        D(5),
    ),
    ParamDef(
        "M1_Z_FLOOR",
        "M1",
        "Минимальный разброс для z-score",
        "п.п.",
        "чтобы почти одинаковая сеть не делала тревогу из мелочи",
        D("0.1"),
        D(5),
        PCT,
    ),
    ParamDef(
        "M1_NET_SHARE",
        "M1",
        "«Виновата техкарта»: доля ресторанов выше нормы",
        "%",
        "от всех ресторанов, закупающих товар",
        D(50),
        D(100),
        PCT,
    ),
    ParamDef(
        "M1_NET_EXCESS",
        "M1",
        "«Виновата техкарта»: типичный ресторан выше допуска на",
        "п.п.",
        "",
        D("0.5"),
        D(20),
        PCT,
    ),
    ParamDef(
        "M1_MIN_THEORY_DAYS",
        "M1",
        "Минимальный период между инвентаризациями",
        "дней",
        "короче — слишком мало данных",
        D(7),
        D(90),
    ),
    ParamDef(
        "M1_NET_ALIGN_DAYS",
        "M1",
        "С сетью сравниваем периоды, закончившиеся не дальше чем через",
        "дней",
        "у ресторанов свои дни инвентаризаций: берем ближайший период каждого",
        D(0),
        D(92),
    ),
    ParamDef(
        "M1_UNDER",
        "M1",
        "«Расход меньше техкарты»: насколько меньше",
        "%",
        "риск, что гость получает меньше положенного, или не учтен приход",
        D(1),
        D(50),
        PCT,
    ),
    ParamDef("M2_WINDOW_DAYS", "M2", "Текущие цены закупки — за последние", "дней", "", D(7), D(90)),
    ParamDef(
        "M2_COMPARE_DAYS",
        "M2",
        "С чем сравниваем, чтобы назвать причину",
        "дней назад",
        "«квартал назад»",
        D(28),
        D(365),
    ),
    ParamDef(
        "M2_KEEP",
        "M2",
        "Доля разницы в потенциале",
        "%",
        "консервативно: часть гостей после подорожания закажет другое",
        D(10),
        D(100),
        PCT,
    ),
    ParamDef(
        "M2_MATERIALITY_RUB_MONTH",
        "M2",
        "Ниже какого потенциала не показываем",
        "₽ в месяц",
        "",
        D(0),
        D(100000),
    ),
    ParamDef("M3_WINDOW_DAYS", "M3", "Окно сравнения цен ресторанов", "дней", "", D(14), D(180)),
    ParamDef("M3_OVERPAY", "M3", "Насколько дороже типичной цены сети", "%", "", D(1), D(50), PCT),
    ParamDef(
        "M3_MATERIALITY_RUB_MONTH",
        "M3",
        "Ниже какой переплаты не показываем",
        "₽ в месяц",
        "",
        D(0),
        D(100000),
    ),
    ParamDef("M3_Z", "M3", "Насколько цена должна выделяться (z-score)", "", "", D(1), D(5)),
    ParamDef("M3_Z_FLOOR", "M3", "Минимальный разброс цен для z-score", "%", "", D("0.1"), D(10), PCT),
    ParamDef(
        "M3_MIN_RECEIPTS", "M3", "Минимум закупок товара в окне", "накладных", "у ресторана", D(1), D(20)
    ),
    ParamDef(
        "M3_CONTRACT_TOLERANCE",
        "M3",
        "Допуск к договорной цене",
        "%",
        "округления в накладных",
        D(0),
        D(10),
        PCT,
    ),
    ParamDef(
        "M3_NET_GROWTH",
        "M3",
        "Рост цены по всей сети, при котором это находка",
        "%",
        "к тем же неделям квартал назад",
        D(1),
        D(100),
        PCT,
    ),
    ParamDef("M3_NET_WINDOW_DAYS", "M3", "Окно для роста цены по сети", "дней", "", D(7), D(90)),
    ParamDef("M3_NET_COMPARE_DAYS", "M3", "Сравниваем с периодом", "дней назад", "", D(28), D(365)),
    ParamDef(
        "M4_PRE_DAYS", "M4", "Списания «перед инвентаризацией» — за", "дней до пересчета", "", D(1), D(7)
    ),
    ParamDef(
        "M4_PRE_SHARE",
        "M4",
        "Находка, если в эти дни оформлено не меньше",
        "% списаний",
        "в рублях, с первой инвентаризации",
        D(20),
        D(100),
        PCT,
    ),
    ParamDef(
        "M4_PRE_TIMES",
        "M4",
        "…и во столько раз больше, чем при списаниях в день порчи",
        "раза",
        "",
        D(1),
        D(20),
    ),
    ParamDef(
        "M4_SORT_SHARE",
        "M4",
        "Пересорт: излишек товара к учету не меньше",
        "%",
        "на последней инвентаризации",
        D(1),
        D(100),
        PCT,
    ),
    ParamDef(
        "M4_SORT_MATCH",
        "M4",
        "Пересорт: недостача другого товара той же категории отличается от излишка не больше чем на",
        "%",
        "",
        D(5),
        D(100),
        PCT,
    ),
    ParamDef("M5_WINDOW_DAYS", "M5", "Списания и закупки сравниваем за последние", "дней", "", D(14), D(90)),
    ParamDef(
        "M5_TIMES",
        "M5",
        "Списания выше сети: во сколько раз больше медианы сети",
        "раза",
        "списано / закуплено",
        D("1.2"),
        D(10),
    ),
    ParamDef("M5_EXCESS", "M5", "…и больше хотя бы на", "п.п.", "", D("0.5"), D(50), PCT),
    ParamDef(
        "M5_WEEKDAY_SHARE",
        "M5",
        "По дням недели: два соседних дня держат не меньше",
        "% списаний",
        "ровно по дням было бы 29%",
        D(30),
        D(100),
        PCT,
    ),
    ParamDef("M5_WEEKDAY_WEEKS", "M5", "…и так повторяется недель", "из окна", "", D(1), D(12)),
    ParamDef(
        "M5_MATERIALITY_RUB_MONTH", "M5", "Ниже каких потерь не показываем", "₽ в месяц", "", D(0), D(100000)
    ),
    ParamDef(
        "M7_WINDOW_DAYS", "M7", "Блюда без техкарты ищем в продажах за последние", "дней", "", D(7), D(90)
    ),
    ParamDef(
        "M7_GAP_DAYS",
        "M7",
        "Выгрузка не загружена, если данных нет хотя бы",
        "дней",
        "при том что другие рестораны уже загрузили эти дни",
        D(2),
        D(60),
    ),
    ParamDef(
        "M7_GAP_TIMES",
        "M7",
        "…и пауза длиннее обычной для ресторана в",
        "раза",
        "закупки бывают не каждый день: сравниваем с обычной паузой за 8 недель",
        D(1),
        D(10),
    ),
)
BY_KEY = {d.key: d for d in DEFS}
assert set(BY_KEY) <= {f.name for f in fields(EngineParams)}


def from_overrides(overrides: dict[str, Any] | None) -> EngineParams:
    """Defaults with a network's own values on top (stored in engine units, as strings)."""
    known = {k: v for k, v in (overrides or {}).items() if k in BY_KEY}
    values: dict[str, Any] = {}
    for key, raw in known.items():
        values[key] = int(raw) if isinstance(getattr(DEFAULT, key), int) else Decimal(str(raw))
    return replace(DEFAULT, **values)


def load(session: Session) -> EngineParams:
    from app.norms.models import NormSettings  # norms own the table; analytics only reads it

    overrides = session.execute(select(NormSettings.engine_params)).scalar_one_or_none()
    return from_overrides(overrides)
