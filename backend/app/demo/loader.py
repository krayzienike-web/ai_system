"""Loading the demo network through the same pipeline a user goes through: upload → validate → publish."""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.core.errors import InvalidError
from app.demo.generator import DemoNetwork, load_plan
from app.imports import service
from app.imports.models import BatchStatus
from app.tenancy.context import AccessContext
from app.tenancy.models import Restaurant


def load(session: Session, ctx: AccessContext, net: DemoNetwork, *, today: date) -> dict[str, int]:
    """Publishes every file of the network as `ctx` (an HQ admin). Returns published rows per template."""
    published: dict[str, int] = {}
    for template, code, name in load_plan(net):
        restaurant_id = None
        if code is not None:
            restaurant_id = session.execute(select(Restaurant.id).where(Restaurant.code == code)).scalar_one()
        batch = service.upload(
            session,
            ctx,
            template_name=template,
            restaurant_id=restaurant_id,
            filename=name,
            raw=net.files[name],
            today=today,
        )
        if batch.status == BatchStatus.NEEDS_MATCHING:
            # What a person does once: confirm what the other system's names are (generator's answer key).
            codes = {p.code: p.id for p in session.execute(select(Product)).scalars()}
            matches = [(u["kind"], u["key"], codes[net.name_matches[u["name"]]]) for u in batch.unmatched]
            batch = service.match(session, ctx, batch.id, matches, today=today)
        if batch.status != BatchStatus.VALIDATED:
            raise InvalidError(f"{name}: {batch.errors[:3]} {batch.unmatched[:3]}")
        service.publish(session, ctx, batch.id, today=today)
        published[template] = published.get(template, 0) + batch.rows_valid
    _unit_example(session, ctx, today)
    return published


# 1С's purchases of R03 for the day after the demo's data, in packs and bottles (Q35). The file stays
# unloaded, so «Данные» shows how a unit is fixed: set the factor on the report, then «Проверить заново».
UNIT_EXAMPLE_NAME = "Приходы 1С R03 19.10.csv"
UNIT_EXAMPLE = (
    "Дата;№ накладной;Код поставщика;Поставщик;Код товара;Товар;Количество;Ед. изм.;Цена;Сумма;НДС\n"
    "19.10.2026;ПМ-1901;S3;Молочный двор;P04;Сливки 33%;12;упак;360,00;4320,00;20\n"
    "19.10.2026;ПМ-1902;S7;Бакалея Опт;P14;Масло оливковое;6;бут;1100,00;6600,00;20\n"
    "19.10.2026;ПМ-1902;S7;Бакалея Опт;P15;Паста спагетти;10;кг;190,00;1900,00;20\n"
)


def _unit_example(session: Session, ctx: AccessContext, today: date) -> None:
    r03 = session.execute(select(Restaurant.id).where(Restaurant.code == "R03")).scalar_one()
    batch = service.upload(
        session,
        ctx,
        template_name="receipts",
        restaurant_id=r03,
        filename=UNIT_EXAMPLE_NAME,
        raw=UNIT_EXAMPLE.encode(),
        today=today,
    )
    if batch.status != BatchStatus.FAILED:
        raise InvalidError(f"{UNIT_EXAMPLE_NAME}: expected the unknown units, got {batch.status}")
    # The network loads in one transaction, so every file has its start time: this one is the latest upload
    # and heads «Что загружали?».
    batch.created_at = datetime.now(UTC)
