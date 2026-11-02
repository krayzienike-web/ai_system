"""The demo stand (docs/06, stage 5; deploy/): the demo's calendar, the nightly rebuild and its guard."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

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
    assert [j.name for j in worker.cron_jobs()] == ["cron:weekly_digests"]
    settings_env(FAI_DEMO_RESET_NIGHTLY="true")
    _, job = worker.cron_jobs()
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


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _caddy_block(caddyfile: str, matcher: str) -> str:
    """The body of `handle <matcher> { … }` (braces counted)."""
    start = caddyfile.index(f"handle {matcher}".rstrip() + " {")
    depth, i = 0, caddyfile.index("{", start)
    for j in range(i, len(caddyfile)):
        depth += {"{": 1, "}": -1}.get(caddyfile[j], 0)
        if depth == 0:
            return caddyfile[i + 1 : j]
    raise AssertionError(f"unclosed handle {matcher}")


def test_the_stand_streams_the_chat_and_never_serves_a_missing_chunk_as_the_page() -> None:
    """Code review 28.10.2026, stage 5: the API is not compressed and not buffered (the chat's SSE events pass
    at once, p. 17); a missing chunk is 404, not index.html cached for a year (frontend p. 1); the page is
    revalidated."""
    caddy = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    code = "\n".join(line.split("#")[0] for line in caddy.splitlines())  # without the comments
    api, assets, page = _caddy_block(code, "/api/*"), _caddy_block(code, "/assets/*"), _caddy_block(code, "")
    assert "encode" not in api and "flush_interval -1" in api
    assert "try_files" not in assets and "immutable" in assets
    assert "try_files {path} /index.html" in page and 'Cache-Control "no-cache"' in page


def test_only_the_api_gets_the_models_key() -> None:
    """Code review 28.10.2026, stage 5, p. 16: not `migrate`, not `worker`."""
    compose = (DEPLOY / "compose.yml").read_text(encoding="utf-8")
    services: dict[str, str] = {}
    name = ""
    for line in compose.split("\nvolumes:")[0].splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
            name = line.strip().rstrip(":")
        elif name:
            services[name] = services.get(name, "") + line + "\n"
    assert {"migrate", "backend", "worker"} <= set(services)
    assert [s for s, body in services.items() if "ANTHROPIC_API_KEY" in body] == ["backend"]
    assert "ANTHROPIC_API_KEY" not in compose.split("environment: &backend-env")[1].split("command:")[0]
