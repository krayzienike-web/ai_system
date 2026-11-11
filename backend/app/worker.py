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

from app.agents import service as agents
from app.ai import agent_writer, digest_writer
from app.ai.gateway import get_gateway
from app.analytics import runs
from app.core.config import get_settings
from app.core.period import get_today
from app.digests import weekly
from app.imports import retention


async def run_engine(ctx: dict[str, Any], run_id: str, tenant_id: str, today: str) -> None:
    await asyncio.to_thread(runs.execute, UUID(run_id), UUID(tenant_id), date.fromisoformat(today))


async def reset_demo(ctx: dict[str, Any]) -> None:
    """The demo stand's nightly rebuild (FAI_DEMO_RESET_NIGHTLY). A separate process: the product does not
    import the demo (import-linter), and a failed rebuild does not take the worker down."""
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.cli", "reset-demo")
    if await process.wait() != 0:
        raise RuntimeError(f"reset-demo exited with {process.returncode}")


def build_digests(today: date) -> int:
    """Every network's digests of the week before `today` that are not there yet; the texts by the model when
    it is on. Run at 08:31 and caught up hourly until 14:31 (a restarted worker loses no week)."""
    gateway = get_gateway()
    writer_for = (lambda ctx: digest_writer.writer(gateway, ctx)) if gateway is not None else None
    return sum(weekly.run(tenant_id, today, writer_for, only_missing=True) for tenant_id in weekly.tenants())


async def weekly_digests(ctx: dict[str, Any]) -> None:
    await asyncio.to_thread(build_digests, get_today())


def run_agents(today: date) -> int:
    """The agents' morning pass over every network (stage 9, ADR 0010); texts by the model when it is on."""
    gateway = get_gateway()
    write_for = (lambda ctx: agent_writer.writer(gateway, ctx)) if gateway is not None else None
    return agents.run_all(today, write_for)


async def morning_agents(ctx: dict[str, Any]) -> None:
    await asyncio.to_thread(run_agents, get_today())


async def sweep_runs(ctx: dict[str, Any]) -> None:
    await asyncio.to_thread(runs.sweep, get_today())


async def purge_files(ctx: dict[str, Any]) -> None:
    await asyncio.to_thread(retention.purge_all)


def cron_jobs() -> list[CronJob]:
    # The digests: Monday 08:31 Moscow time (05:31 UTC), about the week before (Q24; off the round minute),
    # then every hour until 14:31 for what is still missing (code review 03.11.2026, p. 17).
    jobs = [
        cron(weekly_digests, weekday={0}, hour=set(range(5, 12)), minute={31}, timeout=3600),
        # Runs lost with the queue or left by a dead process (pre-pilot review 10.11.2026, p. 20)
        cron(sweep_runs, minute=set(range(3, 60, 10)), timeout=int(runs.JOB_TIMEOUT.total_seconds())),
        # The agents: every morning at 08:47 Moscow time (05:47 UTC), before the director's day (Q38). Fixed
        # in UTC like the digests: a network in another zone (FAI_TIMEZONE) still gets them at 05:47 UTC
        cron(morning_agents, hour={5}, minute={47}, timeout=3600),
        # Source files past their retention period: 03:37 Moscow time (00:37 UTC; p. 18)
        cron(purge_files, hour={0}, minute={37}, timeout=1800),
    ]
    if get_settings().demo_reset_nightly:  # 03:07 Moscow time (00:07 UTC): nobody looks at the demo then
        jobs.append(cron(reset_demo, hour={0}, minute={7}, timeout=1800))
    return jobs


class WorkerSettings:
    functions = [run_engine]  # noqa: RUF012  (arq reads class attributes)
    cron_jobs = cron_jobs()
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
    # A run stops before it would count as interrupted (runs.STALE): never two runs of one network at once
    job_timeout = int(runs.JOB_TIMEOUT.total_seconds())
