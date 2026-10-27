"""The background worker (arq + Redis): `arq app.worker.WorkerSettings`.

It runs the engine after uploads (`app/analytics/runs.py`). The work itself is synchronous (SQLAlchemy),
so it runs in a thread; runs of one network are serialized by the engine's lock.
"""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings

from app.analytics import runs
from app.core.config import get_settings


async def run_engine(ctx: dict[str, Any], run_id: str, tenant_id: str, today: str) -> None:
    await asyncio.to_thread(runs.execute, UUID(run_id), UUID(tenant_id), date.fromisoformat(today))


class WorkerSettings:
    functions = [run_engine]  # noqa: RUF012  (arq reads class attributes)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
