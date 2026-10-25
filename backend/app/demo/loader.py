"""Loading the demo network through the same pipeline a user goes through: upload → validate → publish."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        if batch.status != BatchStatus.VALIDATED:
            raise InvalidError(f"{name}: {batch.errors[:3]}")
        service.publish(session, ctx, batch.id, today=today)
        published[template] = published.get(template, 0) + batch.rows_valid
    return published
