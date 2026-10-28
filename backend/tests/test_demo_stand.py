"""The demo stand (docs/06, stage 5; deploy/): the demo's calendar, the nightly rebuild and its guard."""

from collections.abc import Callable, Iterator
from datetime import date

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import cli, worker
from app.core.config import get_settings
from app.core.period import get_today
from app.tenancy.models import Tenant
from tests.conftest import Network

Env = Callable[..., None]


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    def use(**env: str) -> None:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield use
    get_settings.cache_clear()


def test_the_stand_lives_on_the_demos_today(settings_env: Env) -> None:
    assert get_today() == date.today()
    settings_env(FAI_DEMO_TODAY="2026-10-20")
    assert get_today() == date(2026, 10, 20)


def test_the_nightly_rebuild_is_scheduled_only_on_the_stand(settings_env: Env) -> None:
    assert worker.cron_jobs() == []
    settings_env(FAI_DEMO_RESET_NIGHTLY="true")
    (job,) = worker.cron_jobs()
    assert (job.hour, job.minute) == ({0}, {7})  # 03:07 Moscow


def test_the_rebuild_refuses_a_database_with_other_networks(network: Network, owner_engine: Engine) -> None:
    with pytest.raises(SystemExit, match="Not a demo stand"):
        cli.reset_demo("x", 42)
    with Session(owner_engine) as s:
        assert s.execute(select(func.count()).select_from(Tenant)).scalar_one() == 2  # nothing was removed


def test_the_stand_refuses_the_prototypes_demo_password(settings_env: Env) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="FAI_DEMO_PASSWORD"):
        Settings(env="prod", jwt_secret="x" * 40, demo_reset_nightly=True)
    assert (
        Settings(env="prod", jwt_secret="x" * 40, demo_reset_nightly=True, demo_password="s3cret-pass").env
        == "prod"
    )


def test_the_rebuild_brings_the_demo_network_back_as_on_the_first_day(owner_engine: Engine) -> None:
    """Code review 28.10.2026, stage 5, p. 14: the full cycle — whatever visitors changed is gone."""
    from sqlalchemy import text

    from app.insights.models import Finding
    from app.tenancy.models import User

    with owner_engine.begin() as conn:
        conn.execute(text("TRUNCATE tenants CASCADE"))
    cli.reset_demo("demo-pass-1", 42)
    with Session(owner_engine) as s:
        findings = s.execute(select(func.count()).select_from(Finding)).scalar_one()
        s.execute(text("UPDATE findings SET title = 'изменил посетитель'"))
        s.commit()
    cli.reset_demo("demo-pass-1", 42)
    with Session(owner_engine) as s:
        assert s.execute(select(Tenant.name)).scalars().all() == [cli.DEMO_TENANT]
        assert s.execute(select(func.count()).select_from(User)).scalar_one() == 5
        assert s.execute(select(func.count()).select_from(Finding)).scalar_one() == findings > 0
        assert not s.execute(select(Finding).where(Finding.title == "изменил посетитель")).first()
