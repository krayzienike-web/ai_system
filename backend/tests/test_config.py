"""Architecture review 27.10.2026, p. 3: without FAI_ENV the settings are production (no dev secret)."""

import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings


def test_without_an_environment_the_settings_are_production_and_refuse_the_dev_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAI_ENV", raising=False)
    monkeypatch.delenv("FAI_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="FAI_JWT_SECRET must be set"):
        Settings(_env_file=None)
    assert Settings(_env_file=None, jwt_secret="x" * 40).env == "prod"


@pytest.mark.parametrize("env", ["dev", "test"])
def test_development_and_tests_may_use_the_dev_secret(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAI_ENV", env)
    assert Settings(_env_file=None).jwt_secret == DEV_JWT_SECRET
