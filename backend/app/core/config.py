from datetime import date
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-secret-change-me-dev-secret-change-me"  # noqa: S105  (dev only, refused outside dev)
DEV_DEMO_PASSWORD = "demo12345"  # noqa: S105  (the prototype's public logins; the demo stand sets its own)
DEV_CASHIER_KEY = "dev-cashier-key"  # dev and tests only: a real network's codes need its own key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FAI_", extra="ignore")

    # Production unless said otherwise: a server started without FAI_ENV refuses the known dev JWT secret
    # (architecture review 27.10.2026, p. 3). Development sets FAI_ENV=dev (Makefile, docker-compose, .env).
    env: str = "prod"

    # The application connects as a role without BYPASSRLS; migrations run as the schema owner.
    database_url: str = "postgresql+psycopg://franchise_app:app@localhost:5432/franchise"
    migrations_database_url: str = "postgresql+psycopg://franchise_owner:owner@localhost:5432/franchise"
    app_db_role: str = "franchise_app"

    jwt_secret: str = Field(default=DEV_JWT_SECRET, min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    # The refresh token lives in an httpOnly cookie (pre-pilot review, p. 5): Secure (HTTPS only) unless said
    # otherwise; not set, dev and tests over plain http go without it.
    cookie_secure: bool | None = None

    # «Today» is the network's day, not the server's UTC one (pre-pilot review, p. 21).
    timezone: str = "Europe/Moscow"

    # A cashier's name becomes a code keyed by this secret (pre-pilot review, p. 19): without the key the code
    # cannot be traced back to a name by trying names.
    cashier_key: str = DEV_CASHIER_KEY

    # How long the source files are kept (pre-pilot review, p. 18; Q37): files that failed the check, and the
    # rest. The batch, its report and the data loaded from it stay.
    file_retention_failed_days: int = 7
    file_retention_days: int = 90

    cors_origins: list[str] = ["http://localhost:5173"]

    # The background queue (arq). Required outside dev/test; not set there: background work runs in the API
    # process after the response.
    redis_url: str | None = None

    # The demo stand (docs/06, stage 5): the calendar stays on the demo's «today», so the data never looks
    # stale, and the worker rebuilds the demo network every night (`app.cli reset-demo`). Not for a real one.
    demo_today: date | None = None
    demo_reset_nightly: bool = False
    demo_password: str = DEV_DEMO_PASSWORD

    # The assistant's model (ADR 0005). `off` until the Claude API key comes (Q12): the chat answers by its
    # rules. `claude` reads the key from ANTHROPIC_API_KEY.
    ai_provider: str = "off"
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_timeout_s: float = 120.0
    ai_requests_per_user_day: int = 100

    @field_validator("demo_today", "redis_url", "demo_reset_nightly", mode="before")
    @classmethod
    def empty_is_unset(cls, value: object, info: ValidationInfo) -> object:
        # compose passes `${DEMO_TODAY:-}`: an empty variable means «not set» (the pilot has no demo calendar)
        if value != "":
            return value
        return False if info.field_name == "demo_reset_nightly" else None

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.env not in ("dev", "test")

    @property
    def is_demo_stand(self) -> bool:
        return self.demo_today is not None or self.demo_reset_nightly

    @model_validator(mode="after")
    def no_dev_secret_outside_dev(self) -> "Settings":
        if self.env in ("dev", "test"):
            return self
        if self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("FAI_JWT_SECRET must be set outside dev/test")
        if self.redis_url is None:
            raise ValueError(
                "FAI_REDIS_URL must be set outside dev/test: recalculations go through the queue"
            )
        if self.cashier_key == DEV_CASHIER_KEY or len(self.cashier_key) < 32:
            raise ValueError("FAI_CASHIER_KEY must be set outside dev/test: 32+ random characters")
        if self.demo_reset_nightly and self.demo_password == DEV_DEMO_PASSWORD:
            raise ValueError("FAI_DEMO_PASSWORD must be set on the demo stand")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"FAI_TIMEZONE: unknown time zone {self.timezone}") from e
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
