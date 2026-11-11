"""№ 9. The morning data check (docs/07 «ИИ-агенты», ADR 0010).

Every morning, per restaurant: which exports are missing — by the rules of «Свежесть данных» on the «Данные»
screen (`imports.service.freshness`): sales, receipts and write-offs with nothing in the last full week,
stock counts never loaded. So the director uploads them before the findings are computed on half the data.
One note a day; when the data comes, the note expires (the next run finds nothing).
"""

from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.drafts import NoteDraft
from app.agents.models import Agent, Audience
from app.imports.service import freshness
from app.tenancy.models import Restaurant


def drafts(session: Session, restaurants: list[Restaurant], today: date) -> list[NoteDraft]:
    places = {r.id: r for r in restaurants}
    missing: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for f in freshness(session, today=today):
        if f["status"] != "good" and f["restaurant_id"] in places:
            last = f["last_date"]
            missing[f["restaurant_id"]].append(
                {"template": f["template"], "status": f["status"], "last_date": last and last.isoformat()}
            )
    return [
        NoteDraft(
            agent=Agent.DATA_CHECK,
            audience=Audience.DIRECTOR,
            restaurant_id=rid,
            key=f"data_check:{places[rid].code}:{today.isoformat()}",
            for_date=today,
            facts={"restaurant": places[rid].name, "today": today.isoformat(), "missing": rows},
        )
        for rid, rows in missing.items()
    ]
