"""The pilot's configuration (stage 8, step 7; pre-pilot review 10.11.2026, pp. 4, 5, 18–21; docs/09).

Sessions in an httpOnly cookie with rotation and sign-out; accounts of the operator with handed-out passwords
changed at the first sign-in; the source files' retention; the sweeper of lost runs; the API that refuses a
database role row-level security would not hold for; the pilot's settings without the demo calendar."""

import subprocess
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from app import cli
from app.analytics import runs
from app.auth import accounts
from app.auth.sessions import AuthSession
from app.core.config import Settings, get_settings
from app.core.db import RlsContext, apply_rls_context, get_sessionmaker, role_problems
from app.core.period import get_today
from app.imports import retention
from app.imports.models import ImportBatch
from app.imports.validate import cashier
from app.main import app, check_database_role
from app.tenancy.models import Role, User
from tests.conftest import PASSWORD, Network, login
from tests.test_config import PROD
from tests.test_imports_api import PRODUCTS, upload

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 25)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Settings from the environment, read again after each change."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _sign_in(client: TestClient, email: str = "admin@a.ru", password: str = PASSWORD) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


def _cookie(client: TestClient) -> str:
    value = client.cookies.get("fai_refresh", path="/api/auth")
    assert value
    return value


def _with_cookie(client: TestClient, value: str) -> None:
    client.cookies.clear()
    client.cookies.set("fai_refresh", value, path="/api/auth")


# --- Session (TC-AUTH-14…17) ---------------------------------------------------------------------------


def test_the_refresh_token_lives_only_in_an_httponly_cookie(client: TestClient, network: Network) -> None:
    """TC-AUTH-14: the body has the access token only; the cookie is httpOnly, SameSite=Strict, for /api/auth;
    Secure in production; the database keeps the token's hash, not the token."""
    r = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": PASSWORD})
    assert set(r.json()) == {"access_token", "token_type", "must_change_password"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/auth" in cookie
    assert "secure" not in cookie  # tests run over http; production sets it (below)
    assert Settings(env="prod", **PROD).secure_cookies
    assert not Settings(env="prod", **PROD, cookie_secure=False).secure_cookies
    with get_sessionmaker()() as s:
        apply_rls_context(s, RlsContext(network.a.id, network.a.users["admin@a.ru"], scope_all=False))
        hashes = list(s.execute(select(AuthSession.token_hash)).scalars())
    assert len(hashes) == 1 and _cookie(client) not in hashes


def test_a_refresh_rotates_the_token_and_a_reused_one_ends_the_sign_in(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-15: every refresh gives a new token; the old one again within 30 s (two tabs) still works,
    later it was copied — the whole sign-in ends, for both holders."""
    _sign_in(client)
    first = _cookie(client)
    assert client.post("/api/auth/refresh").status_code == 200
    second = _cookie(client)
    assert second != first
    _with_cookie(client, first)  # the other tab, a moment later
    assert client.post("/api/auth/refresh").status_code == 200
    with owner_engine.begin() as conn:  # a minute later
        conn.execute(
            update(AuthSession)
            .where(AuthSession.rotated_at.is_not(None))
            .values(rotated_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    _with_cookie(client, first)
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401 and r.json()["detail"] == "Сессия закончилась — войдите снова"
    assert "fai_refresh=" in r.headers["set-cookie"]  # the cookie is removed
    _with_cookie(client, second)
    assert client.post("/api/auth/refresh").status_code == 401  # the thief's copy and the owner's alike


def test_signing_out_ends_the_sign_in(client: TestClient, network: Network, owner_engine: Engine) -> None:
    """TC-AUTH-16: logout revokes the sign-in and removes the cookie; without a cookie it is harmless;
    another device's sign-in stays."""
    other = TestClient(app)
    _sign_in(other)
    _sign_in(client)
    token = _cookie(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 204 and 'fai_refresh=""' in r.headers["set-cookie"]
    _with_cookie(client, token)
    assert client.post("/api/auth/refresh").status_code == 401
    client.cookies.clear()
    assert client.post("/api/auth/logout").status_code == 204
    assert other.post("/api/auth/refresh").status_code == 200
    with owner_engine.connect() as conn:
        actions = list(conn.execute(text("SELECT action FROM audit_log ORDER BY created_at")).scalars())
    assert actions.count("auth.logout") == 1


def test_an_expired_or_disabled_users_cookie_does_not_refresh(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    _sign_in(client)
    with owner_engine.begin() as conn:
        conn.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert client.post("/api/auth/refresh").status_code == 401
    _sign_in(client)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false WHERE email = 'admin@a.ru'"))
    assert client.post("/api/auth/refresh").status_code == 401
    client.cookies.clear()
    assert client.post("/api/auth/refresh").status_code == 401  # no cookie at all


def test_a_new_password_ends_the_other_sign_ins(client: TestClient, network: Network) -> None:
    """TC-AUTH-17: the current password is checked, the new one is 10+ characters and not the same; then every
    other sign-in ends, this one goes on with a new token."""
    laptop = TestClient(app)
    _sign_in(laptop)
    auth = {"Authorization": f"Bearer {_sign_in(client)}"}

    def change(current: str, new: str) -> tuple[int, str]:
        r = client.post(
            "/api/auth/password", headers=auth, json={"current_password": current, "new_password": new}
        )
        return r.status_code, r.json().get("detail", "")

    assert change("wrong-pass-1", "new-password-1") == (400, "Текущий пароль указан неверно")
    assert change(PASSWORD, "short") == (400, "Новый пароль должен быть не короче 10 символов")
    assert change(PASSWORD, PASSWORD) == (400, "Новый пароль должен отличаться от текущего")
    assert change(PASSWORD, "new-password-1")[0] == 200
    assert laptop.post("/api/auth/refresh").status_code == 401
    assert client.post("/api/auth/refresh").status_code == 200
    login(client, "admin@a.ru", "new-password-1")
    r = client.post("/api/auth/login", json={"email": "admin@a.ru", "password": PASSWORD})
    assert r.status_code == 401


# --- Accounts (TC-AUTH-18, 19) ---------------------------------------------------------------------------


def test_a_handed_out_password_is_changed_before_anything_else(client: TestClient, network: Network) -> None:
    """TC-AUTH-18: a login made by the operator signs in, sees who it is, and is asked to change the password;
    every other request is refused until then."""
    issued = accounts.add_user("Сеть А", "new.director@a.ru", "Иванова Е.", Role.RESTAURANT_DIRECTOR, "A1")
    token = client.post("/api/auth/login", json={"email": issued.email, "password": issued.password}).json()
    assert token["must_change_password"] is True
    auth = {"Authorization": f"Bearer {token['access_token']}"}
    assert client.get("/api/auth/me", headers=auth).json()["must_change_password"] is True
    r = client.get("/api/tasks", headers=auth)
    assert r.status_code == 403 and r.headers["x-password-change"] == "required"
    r = client.post(
        "/api/auth/password",
        headers=auth,
        json={"current_password": issued.password, "new_password": "my-own-password"},
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/tasks", headers=auth).status_code == 200


def test_the_operator_manages_the_pilots_logins(
    client: TestClient, network: Network, env: pytest.MonkeyPatch, owner_engine: Engine
) -> None:
    """TC-AUTH-19: a network and its HQ admin; a director with their restaurant; refusals in plain words;
    disabling and resetting end the sign-ins; never a real network on the demo stand."""
    issued = accounts.create_tenant("Пилотная сеть", "hq@pilot.ru", "Петрова А.")
    assert len(issued.password) == 19 and not set(issued.password) & set("01ilo")
    with pytest.raises(accounts.AccountError, match="уже есть"):
        accounts.create_tenant("Пилотная сеть", "x@pilot.ru", "X")
    with pytest.raises(accounts.AccountError, match="уже есть"):
        accounts.add_user("Пилотная сеть", "HQ@pilot.ru", "Y", Role.HQ_ANALYST, None)
    with pytest.raises(accounts.AccountError, match="нет ресторана R01"):
        accounts.add_user("Пилотная сеть", "d@pilot.ru", "D", Role.RESTAURANT_DIRECTOR, "R01")
    with pytest.raises(accounts.AccountError, match="Директору нужен ресторан"):
        accounts.add_user("Пилотная сеть", "d@pilot.ru", "D", Role.RESTAURANT_DIRECTOR, None)
    with pytest.raises(accounts.AccountError, match="только директору"):
        accounts.add_user("Пилотная сеть", "d@pilot.ru", "D", Role.HQ_ANALYST, "R01")
    with pytest.raises(accounts.AccountError, match="Нет сети"):
        accounts.add_user("Нет такой", "d@pilot.ru", "D", Role.HQ_ANALYST, None)
    with pytest.raises(accounts.AccountError, match="email"):
        accounts.add_user("Пилотная сеть", "not-an-email", "D", Role.HQ_ANALYST, None)
    assert accounts.users("Пилотная сеть") == [("hq@pilot.ru", "Петрова А.", "hq_admin", None, True)]

    _sign_in(client, "admin@a.ru")
    assert accounts.set_active("ADMIN@a.ru", False) == 1
    assert client.post("/api/auth/refresh").status_code == 401
    assert accounts.set_active("admin@a.ru", True) == 0
    _sign_in(client, "admin@a.ru")
    reset = accounts.reset_password("admin@a.ru")
    assert client.post("/api/auth/refresh").status_code == 401
    assert (
        client.post("/api/auth/login", json={"email": "admin@a.ru", "password": PASSWORD}).status_code == 401
    )
    assert _sign_in(client, "admin@a.ru", reset.password)
    with Session(owner_engine) as s:
        assert s.execute(select(User.must_change_password).where(User.email == "admin@a.ru")).scalar_one()
    with pytest.raises(accounts.AccountError, match="Нет пользователя"):
        accounts.reset_password("ghost@a.ru")

    env.setenv("FAI_DEMO_TODAY", "2026-10-20")
    get_settings.cache_clear()
    with pytest.raises(accounts.AccountError, match="демо-стенд"):
        accounts.create_tenant("Еще сеть", "y@pilot.ru", "Y")


def test_the_cli_prints_the_password_once_and_refuses_in_plain_words(
    network: Network, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(*argv: str) -> str:
        monkeypatch.setattr("sys.argv", ["app.cli", *argv])
        cli.main()
        return capsys.readouterr().out

    out = run(
        "add-user",
        "--tenant",
        "Сеть А",
        "--email",
        "an2@a.ru",
        "--name",
        "Аналитик 2",
        "--role",
        "hq_analyst",
    )
    assert "an2@a.ru  пароль: " in out and "сменить" in out
    assert "an2@a.ru" in run("list-users", "--tenant", "Сеть А")
    assert "отключен" in run("disable-user", "--email", "an2@a.ru")
    assert "отключен" in run("list-users", "--tenant", "Сеть А")
    assert "включен" in run("enable-user", "--email", "an2@a.ru")
    assert "пароль: " in run("reset-password", "--email", "an2@a.ru")
    with pytest.raises(SystemExit, match="уже есть"):
        run("add-user", "--tenant", "Сеть А", "--email", "an2@a.ru", "--name", "X", "--role", "hq_analyst")


def test_a_user_sees_only_their_own_sign_ins(client: TestClient, network: Network) -> None:
    """TC-ISO-27: sign-ins are a user's own: neither HQ of the same network nor anyone else sees them."""
    _sign_in(TestClient(app), "director1@a.ru")
    _sign_in(TestClient(app), "admin@b.ru")
    _sign_in(client, "admin@a.ru")
    with get_sessionmaker()() as s:
        apply_rls_context(s, RlsContext(network.a.id, network.a.users["admin@a.ru"], scope_all=True))
        seen = set(s.execute(select(AuthSession.user_id)).scalars())
    assert seen == {network.a.users["admin@a.ru"]}


# --- Settings, «today», cashiers (TC-OPS-01…03) ----------------------------------------------------------


def test_the_pilot_needs_its_own_secrets_and_has_no_demo_calendar() -> None:
    """TC-OPS-01: outside dev/test the queue and the cashiers' key are required; empty DEMO_* (compose on the
    pilot) mean «not set»; the time zone must exist."""
    with pytest.raises(ValidationError, match="FAI_REDIS_URL"):
        Settings(env="prod", jwt_secret="x" * 40, cashier_key="k" * 40)
    with pytest.raises(ValidationError, match="FAI_CASHIER_KEY"):
        Settings(env="prod", jwt_secret="x" * 40, redis_url="redis://r")
    with pytest.raises(ValidationError, match="FAI_CASHIER_KEY"):
        Settings(env="prod", **{**PROD, "cashier_key": "short"})
    with pytest.raises(ValidationError, match="FAI_TIMEZONE"):
        Settings(env="prod", **PROD, timezone="Europe/Atlantis")
    pilot = Settings(env="prod", **PROD, demo_today="", demo_reset_nightly="")
    assert pilot.demo_today is None and pilot.demo_reset_nightly is False and not pilot.is_demo_stand
    assert Settings(env="prod", **PROD, demo_today=date(2026, 10, 20)).is_demo_stand


def test_today_is_the_networks_day_not_the_servers(env: pytest.MonkeyPatch) -> None:
    """TC-OPS-02: «today» follows FAI_TIMEZONE — UTC+14 is always a day or two ahead of UTC−12."""
    env.setenv("FAI_TIMEZONE", "Pacific/Kiritimati")
    get_settings.cache_clear()
    ahead = get_today()
    env.setenv("FAI_TIMEZONE", "Etc/GMT+12")
    get_settings.cache_clear()
    assert 1 <= (ahead - get_today()).days <= 2


def test_a_cashiers_code_needs_the_servers_key(env: pytest.MonkeyPatch) -> None:
    """TC-OPS-03 (review p. 19): knowing the network's id is not enough to find whose code it is."""
    code = cashier("Иванова Е.", "tenant-1")
    assert code is not None and len(code) == len("Кассир ") + 8
    env.setenv("FAI_CASHIER_KEY", "another-key-" + "z" * 30)
    get_settings.cache_clear()
    assert cashier("Иванова Е.", "tenant-1") != code
    assert cashier("таб. 104", "tenant-1") == "таб. 104"


# --- Data and operations (TC-OPS-04…08) ------------------------------------------------------------------


@pytest.fixture
def pinned() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _age(owner_engine: Engine, batch_id: str, days: int) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            update(ImportBatch)
            .where(ImportBatch.id == UUID(batch_id))
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )


def test_source_files_are_deleted_after_their_period(
    client: TestClient, network: Network, owner_engine: Engine, pinned: None
) -> None:
    """TC-OPS-04 (review p. 18): a failed file after 7 days, any other after 90; the batch and its data stay,
    and what would read the file again says it is gone. Safe twice."""
    hq = login(client, "admin@a.ru")
    a1 = network.a.restaurants["A1"]
    old_failed = upload(client, hq, "sales", "Дата;Блюдо;Кол-во;Сумма\nвчера;Маргарита;x;y\n", a1).json()
    new_failed = upload(client, hq, "sales", "Дата;Блюдо;Кол-во;Сумма\nзавтра;Маргарита;x;y\n", a1).json()
    products = upload(client, hq, "products", PRODUCTS).json()
    assert client.post(f"/api/imports/{products['id']}/publish", headers=hq).status_code == 200
    waiting = upload(client, hq, "products", PRODUCTS + "P3;Руккола;кг\n").json()
    assert old_failed["status"] == new_failed["status"] == "failed"
    _age(owner_engine, old_failed["id"], 8)
    _age(owner_engine, new_failed["id"], 3)
    _age(owner_engine, products["id"], 91)
    _age(owner_engine, waiting["id"], 30)

    assert retention.purge_all() == 2
    assert retention.purge_all() == 0
    with Session(owner_engine) as s:
        rows = {
            str(b.id): (b.raw_deleted_at is not None, len(b.raw))
            for b in s.execute(select(ImportBatch)).scalars()
        }
        actions = list(s.execute(text("SELECT action FROM audit_log")).scalars())
    assert rows[old_failed["id"]] == (True, 0) and rows[products["id"]] == (True, 0)
    assert rows[new_failed["id"]][0] is False and rows[waiting["id"]][0] is False
    assert "import.files_purged" in actions
    assert len(client.get("/api/catalog/product", headers=hq).json()) == 2  # the data stays
    r = client.post(f"/api/imports/{products['id']}/reprocess", headers=hq)
    assert r.status_code == 422 and "удален по сроку хранения" in r.json()["detail"]


def test_the_sweeper_runs_a_lost_run_and_fails_an_interrupted_one(
    network: Network, owner_engine: Engine
) -> None:
    """TC-OPS-05 (review p. 20): a run waiting for 15 minutes lost its job — the sweeper runs it; one «going
    on» for 40 minutes was interrupted — it is failed. A fresh run is left to its job."""
    now = datetime.now(UTC)
    with owner_engine.begin() as conn:
        for tenant, status, requested, started in (
            (network.a.id, "queued", now - timedelta(minutes=15), None),
            (network.b.id, "running", now - timedelta(minutes=45), now - timedelta(minutes=40)),
            (network.b.id, "queued", now - timedelta(minutes=1), None),
        ):
            conn.execute(
                text(
                    "INSERT INTO analytics_runs (id, tenant_id, trigger, status, requested_at, started_at)"
                    " VALUES (gen_random_uuid(), :t, 'upload', :s, :r, :st)"
                ),
                {"t": tenant, "s": status, "r": requested, "st": started},
            )
    assert runs.sweep(TODAY) == 1
    with Session(owner_engine) as s:
        got = sorted(
            (str(r.tenant_id) == str(network.a.id), r.status)
            for r in s.execute(select(runs.AnalyticsRun)).scalars()
        )
    assert got == [(False, "failed"), (False, "queued"), (True, "done")]


def test_the_worker_schedules_the_sweeper_and_the_purge_and_bounds_a_run() -> None:
    from app import worker

    jobs = {j.name: j for j in worker.cron_jobs()}
    assert jobs["cron:purge_files"].hour == {0} and jobs["cron:purge_files"].minute == {37}
    assert jobs["cron:sweep_runs"].minute == {3, 13, 23, 33, 43, 53}
    assert worker.WorkerSettings.job_timeout < runs.STALE.total_seconds()


def test_the_api_refuses_a_role_rls_would_not_hold_for(owner_engine: Engine, env: pytest.MonkeyPatch) -> None:
    """TC-OPS-06 (review p. 21): the API's role is no superuser, has no BYPASSRLS and owns no table; the
    schema owner, which bypasses row-level security, is refused."""
    with get_sessionmaker()() as s:
        assert role_problems(s) == []
    check_database_role()
    with Session(owner_engine) as s:
        problems = role_problems(s)
    assert any("owns users" in p for p in problems)
    env.setenv("FAI_DATABASE_URL", get_settings().migrations_database_url)
    get_settings.cache_clear()
    from app.core.db import get_engine

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Row-level security would not hold"):
            check_database_role()
    finally:
        env.undo()
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()


def test_the_demo_network_stays_on_the_demo_stand(
    env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-OPS-07 (review p. 21): seed-demo takes FAI_DEMO_PASSWORD, never a built-in one, and refuses in
    production without the demo calendar."""
    env.setenv("FAI_ENV", "prod")
    env.setenv("FAI_JWT_SECRET", "x" * 40)
    env.setenv("FAI_REDIS_URL", "redis://r")
    env.setenv("FAI_CASHIER_KEY", "k" * 40)
    get_settings.cache_clear()
    monkeypatch.setattr("sys.argv", ["app.cli", "seed-demo"])
    with pytest.raises(SystemExit, match="only on the demo stand"):
        cli.main()


def test_the_pilots_deployment_files() -> None:
    """TC-OPS-08: the image runs as a user, not root; compose has no demo defaults and mounts the backup
    script; the pilot's example has no DEMO_*; the backup script parses."""
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert "USER app" in dockerfile and dockerfile.index("USER app") < dockerfile.index("CMD")
    compose = (ROOT / "deploy" / "compose.yml").read_text()
    assert "FAI_DEMO_TODAY: ${DEMO_TODAY:-}" in compose
    assert "FAI_CASHIER_KEY: ${CASHIER_KEY:?" in compose and "./db-backup.sh:/usr/local/bin" in compose
    pilot = (ROOT / "deploy" / ".env.pilot.example").read_text()
    assert not [line for line in pilot.splitlines() if line.startswith("DEMO_")]
    assert "CASHIER_KEY=" in pilot and "TIMEZONE=" in pilot
    assert "CASHIER_KEY=" in (ROOT / "deploy" / ".env.example").read_text()
    subprocess.run(["bash", "-n", str(ROOT / "deploy" / "db-backup.sh")], check=True)  # noqa: S603, S607


# --- Edge cases of the pilot's configuration (test pass 11.11.2026; TC-AUTH-20…26, TC-OPS-10…13) -----------


def _owner_waits_on_a_lock(owner_engine: Engine, deadline: float = 10.0) -> None:
    """Until some transaction of this database waits for a lock (the second request of a race)."""
    import time

    started = time.monotonic()
    while time.monotonic() - started < deadline:
        with owner_engine.connect() as conn:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE NOT l.granted AND a.datname = current_database()"
                )
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("the second transaction never waited for the lock")


def _as_user(network: Network, email: str = "admin@a.ru") -> Session:
    from app.tenancy.context import load_access_context

    s = get_sessionmaker()()
    assert load_access_context(s, network.a.users[email], network.a.id) is not None
    return s


def test_two_refreshes_of_one_token_at_once_both_go_on(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-20: two tabs refresh the same token at the same moment: the second waits for the first (FOR
    UPDATE), sees the token already replaced within its 30 s and gets a token of its own; the sign-in stays
    one family, the replaced token keeps the time of its first replacement."""
    import threading

    from app.auth import sessions

    _sign_in(client)
    token = _cookie(client)
    first = get_sessionmaker()()
    second = get_sessionmaker()()
    out: dict[str, object] = {}

    def other_tab() -> None:
        try:
            out["token"] = sessions.rotate(second, token).token
            second.commit()
        except Exception as e:  # pragma: no cover - reported by the assert below
            out["error"] = e

    try:
        mine = sessions.rotate(first, token).token  # holds the token's row
        tab = threading.Thread(target=other_tab)
        tab.start()
        _owner_waits_on_a_lock(owner_engine)
        first.commit()
        tab.join(10)
    finally:
        first.close()
        second.close()
    assert "error" not in out and out["token"] not in (mine, token)
    with Session(owner_engine) as s:
        rows = list(s.execute(select(AuthSession)).scalars())
    assert len(rows) == 3 and len({r.family_id for r in rows}) == 1
    assert [r.revoked_at for r in rows] == [None, None, None]
    for value in (mine, out["token"]):
        _with_cookie(client, str(value))
        assert client.post("/api/auth/refresh").status_code == 200


def test_a_new_password_while_another_tab_refreshes_still_ends_it(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-21: a new password (or reset-password, disable-user) ends every sign-in, also one whose token
    is being replaced at that very moment: the token the refresh hands out must not outlive the change."""
    import threading

    from app.auth import sessions

    _sign_in(client)
    token = _cookie(client)
    refreshing = get_sessionmaker()()
    changing = _as_user(network)
    out: dict[str, object] = {}

    def change_password() -> None:
        try:
            out["ended"] = sessions.end_all(changing, network.a.users["admin@a.ru"])
            changing.commit()
        except Exception as e:  # pragma: no cover - reported by the assert below
            out["error"] = e

    try:
        fresh = sessions.rotate(refreshing, token).token  # the other tab's refresh, not committed yet
        worker = threading.Thread(target=change_password)
        worker.start()
        _owner_waits_on_a_lock(owner_engine)
        refreshing.commit()
        worker.join(10)
    finally:
        refreshing.close()
        changing.close()
    assert "error" not in out
    _with_cookie(client, fresh)
    assert client.post("/api/auth/refresh").status_code == 401


def test_signing_out_while_another_tab_refreshes_ends_both(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-22: one tab signs out with the token replaced a moment ago while the other tab is replacing its
    successor: the token that refresh hands out must not outlive the sign-out."""
    import threading

    from app.auth import sessions

    _sign_in(client)
    replaced = _cookie(client)
    assert client.post("/api/auth/refresh").status_code == 200
    successor = _cookie(client)
    refreshing = get_sessionmaker()()
    signing_out = get_sessionmaker()()
    out: dict[str, object] = {}

    def sign_out() -> None:
        try:
            out["ctx"] = sessions.end(signing_out, replaced)
            signing_out.commit()
        except Exception as e:  # pragma: no cover - reported by the assert below
            out["error"] = e

    try:
        fresh = sessions.rotate(refreshing, successor).token
        worker = threading.Thread(target=sign_out)
        worker.start()
        _owner_waits_on_a_lock(owner_engine)
        refreshing.commit()
        worker.join(10)
    finally:
        refreshing.close()
        signing_out.close()
    assert "error" not in out and out["ctx"] is not None
    _with_cookie(client, fresh)
    assert client.post("/api/auth/refresh").status_code == 401


def test_a_reset_password_ends_a_token_still_in_its_grace(client: TestClient, network: Network) -> None:
    """TC-AUTH-23: the 30 s of a replaced token do not outlive a reset password: neither the replaced token
    nor its successor refreshes."""
    _sign_in(client)
    replaced = _cookie(client)
    assert client.post("/api/auth/refresh").status_code == 200
    successor = _cookie(client)
    accounts.reset_password("admin@a.ru")
    for value in (replaced, successor):
        _with_cookie(client, value)
        assert client.post("/api/auth/refresh").status_code == 401


def test_signing_out_with_a_replaced_token_ends_the_whole_sign_in(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-24: a tab still holding the token replaced a moment ago (or long ago) signs out: the sign-in
    ends with all its tokens, the successor included; each sign-out is audited once."""
    for age in (timedelta(seconds=0), timedelta(minutes=5)):
        client.cookies.clear()
        _sign_in(client)
        replaced = _cookie(client)
        assert client.post("/api/auth/refresh").status_code == 200
        successor = _cookie(client)
        with owner_engine.begin() as conn:
            conn.execute(
                update(AuthSession)
                .where(AuthSession.rotated_at.is_not(None))
                .values(rotated_at=datetime.now(UTC) - age)
            )
        _with_cookie(client, replaced)
        assert client.post("/api/auth/logout").status_code == 204
        _with_cookie(client, successor)
        assert client.post("/api/auth/refresh").status_code == 401
    with owner_engine.connect() as conn:
        actions = list(conn.execute(text("SELECT action FROM audit_log")).scalars())
        alive = conn.execute(text("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL")).scalar_one()
    assert actions.count("auth.logout") == 2 and alive == 0


def test_signing_out_with_a_disabled_users_cookie(
    client: TestClient, network: Network, owner_engine: Engine
) -> None:
    """TC-AUTH-25: the login was disabled while the browser kept its cookie: signing out still answers 204 and
    removes the cookie; after the login is enabled again the old cookie does not come back to life."""
    _sign_in(client)
    token = _cookie(client)
    assert accounts.set_active("admin@a.ru", False) == 1
    _with_cookie(client, token)
    r = client.post("/api/auth/logout")
    assert r.status_code == 204 and 'fai_refresh=""' in r.headers["set-cookie"]
    accounts.set_active("admin@a.ru", True)
    _with_cookie(client, token)
    assert client.post("/api/auth/refresh").status_code == 401
    with owner_engine.connect() as conn:
        actions = list(conn.execute(text("SELECT action FROM audit_log")).scalars())
    assert "auth.logout" not in actions  # nobody signed out: the login was disabled


def test_a_handed_out_password_refreshes_but_does_not_reach_the_chat(
    client: TestClient, network: Network
) -> None:
    """TC-AUTH-26: with a handed-out password the session survives a reload (refresh answers, and says the
    password is to be changed), but the chat — also its stream — refuses with `X-Password-Change`."""
    issued = accounts.add_user("Сеть А", "new.analyst@a.ru", "Новый аналитик", Role.HQ_ANALYST, None)
    _sign_in(client, issued.email, issued.password)
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    question = {"question": "Почему вырос фудкост?"}
    for method, path, body in (
        ("POST", "/api/chat/stream", question),
        ("POST", "/api/chat", question),
        ("GET", "/api/chat/threads", None),
        ("GET", "/api/chat/suggestions", None),
    ):
        r = client.request(method, path, headers=auth, json=body)
        assert r.status_code == 403 and r.headers["x-password-change"] == "required", path


def test_a_rollback_that_needs_a_deleted_file_changes_nothing(
    client: TestClient, network: Network, owner_engine: Engine, pinned: None
) -> None:
    """TC-OPS-10 (review p. 18): rolling back a later file would rebuild its days from an earlier file whose
    source is deleted — the rollback refuses, names the file, and the data stay as they were. The deleted
    file's own batch can still be rolled back (its days are not read again)."""
    from tests.test_imports_api import MENU, _sales, _sales_by_day, publish

    hq, a1 = login(client, "admin@a.ru"), network.a.restaurants["A1"]
    for template, content in (("products", PRODUCTS), ("menu_items", MENU)):
        publish(client, hq, upload(client, hq, template, content).json()["id"])
    early = upload(client, hq, "sales", _sales(("01", 1), ("02", 1), ("03", 1)), a1, "early.csv").json()
    publish(client, hq, early["id"])
    _age(owner_engine, early["id"], 91)
    assert retention.purge_all() == 1
    late = upload(client, hq, "sales", _sales(("02", 5), ("03", 5), ("04", 5)), a1, "late.csv").json()
    publish(client, hq, late["id"])
    both = {"01.10": 1, "02.10": 5, "03.10": 5, "04.10": 5}
    assert _sales_by_day(owner_engine) == both

    r = client.post(f"/api/imports/{late['id']}/rollback", headers=hq)
    assert r.status_code == 422
    assert "«early.csv»" in r.json()["detail"] and "удален по сроку хранения" in r.json()["detail"]
    assert _sales_by_day(owner_engine) == both  # nothing half-done
    assert client.get(f"/api/imports/{late['id']}", headers=hq).json()["status"] == "published"

    r = client.post(f"/api/imports/{early['id']}/rollback", headers=hq)
    assert r.status_code == 200 and r.json()["status"] == "rolled_back"
    assert _sales_by_day(owner_engine) == {"02.10": 5, "03.10": 5, "04.10": 5}


def test_the_nightly_jobs_with_no_networks_do_nothing(owner_engine: Engine) -> None:
    """TC-OPS-11: a fresh installation without a single network: the sweeper and the purge pass quietly."""
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 0
    assert runs.sweep(TODAY) == 0
    assert retention.purge_all() == 0


def test_a_table_without_row_level_security_stops_the_api(owner_engine: Engine) -> None:
    """TC-OPS-12 (review p. 21): a table a migration forgot to protect is named, and the API does not start;
    the app's role neither owns it nor is otherwise suspect."""
    with owner_engine.begin() as conn:
        conn.execute(text("CREATE TABLE forgotten_rls (id int)"))
    try:
        with get_sessionmaker()() as s:
            assert role_problems(s) == ["forgotten_rls has no row-level security"]
        with pytest.raises(RuntimeError, match="forgotten_rls has no row-level security"):
            check_database_role()
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DROP TABLE forgotten_rls"))
    check_database_role()


def test_empty_pilot_secrets_are_missing_secrets() -> None:
    """TC-OPS-13: compose passes an unset variable as an empty string: an empty queue address or cashier key
    is refused just like a missing one, not taken for a value."""
    with pytest.raises(ValidationError, match="FAI_REDIS_URL"):
        Settings(env="prod", **{**PROD, "redis_url": ""})
    with pytest.raises(ValidationError, match="FAI_CASHIER_KEY"):
        Settings(env="prod", **{**PROD, "cashier_key": ""})
    with pytest.raises(ValidationError, match="FAI_TIMEZONE"):
        Settings(env="prod", **PROD, timezone="")


def test_one_failing_network_does_not_stop_the_nightly_jobs(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-OPS-14: the sweeper and the purge go network by network; one failing is logged, the rest run."""
    seen: list[UUID] = []

    def flaky_sweep(tenant_id: UUID, today: date) -> int:
        seen.append(tenant_id)
        if tenant_id == network.a.id:
            raise RuntimeError("broken network")
        return 1

    monkeypatch.setattr(runs, "_sweep_network", flaky_sweep)
    assert runs.sweep(TODAY) == 1 and set(seen) == {network.a.id, network.b.id}

    purged: list[UUID] = []

    def flaky_purge(session: Session, tenant_id: UUID, now: datetime) -> int:
        purged.append(tenant_id)
        if tenant_id == network.a.id:
            raise RuntimeError("broken network")
        return 2

    monkeypatch.setattr(retention, "purge", flaky_purge)
    assert retention.purge_all() == 2 and set(purged) == {network.a.id, network.b.id}


def test_an_unknown_time_zone_is_refused_in_development_too() -> None:
    """TC-OPS-15: a wrong FAI_TIMEZONE would break every «today»: refused in dev and tests as in prod."""
    for env in ("dev", "test"):
        with pytest.raises(ValidationError, match="FAI_TIMEZONE"):
            Settings(env=env, timezone="Europe/Atlantis")
