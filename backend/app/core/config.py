from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-secret-change-me-dev-secret-change-me"  # noqa: S105  (dev only, refused outside dev)


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

    cors_origins: list[str] = ["http://localhost:5173"]

    # The background queue (arq). Not set: background work runs in the API process after the response.
    redis_url: str | None = None

    # The assistant's model (ADR 0005). `off` until the Claude API key comes (Q12): the chat answers by its
    # rules. `claude` reads the key from ANTHROPIC_API_KEY.
    ai_provider: str = "off"
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_timeout_s: float = 60.0
    ai_requests_per_user_day: int = 100

    @model_validator(mode="after")
    def no_dev_secret_outside_dev(self) -> "Settings":
        if self.env not in ("dev", "test") and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("FAI_JWT_SECRET must be set outside dev/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
