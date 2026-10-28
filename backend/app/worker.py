"""The background worker (arq + Redis): `arq app.worker.WorkerSettings`.

It runs the engine after uploads (`app/analytics/runs.py`). The work itself is synchronous (SQLAlchemy),
so it runs in a thread; runs of one network are serialized by the engine's lock.
"""

import asyncio
import sys
from datetime import date
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from arq.cron import CronJob, cron

from app.analytics import runs
from app.core.config import get_settings


async def run_engine(ctx: dict[str, Any], run_id: str, tenant_id: str, today: str) -> None:
    await asyncio.to_thread(runs.execute, UUID(run_id), UUID(tenant_id), date.fromisoformat(today))


async def reset_demo(ctx: dict[str, Any]) -> None:
    """The demo stand's nightly rebuild (FAI_DEMO_RESET_NIGHTLY). A separate process: the product does not
    import the demo (import-linter), and a failed rebuild does not take the worker down."""
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.cli", "reset-demo")
    if await process.wait() != 0:
        raise RuntimeError(f"reset-demo exited with {process.returncode}")


def cron_jobs() -> list[CronJob]:
    # 03:07 Moscow time (00:07 UTC): nobody is looking at the demo then.
    return [cron(reset_demo, hour={0}, minute={7}, timeout=1800)] if get_settings().demo_reset_nightly else []


class WorkerSettings:
    functions = [run_engine]  # noqa: RUF012  (arq reads class attributes)
    cron_jobs = cron_jobs()
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
