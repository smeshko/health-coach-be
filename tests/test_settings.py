"""Settings load + validation tests (E1·P1 TASK-003).

`_env_file=None` disables `.env` discovery so these assertions exercise pure
process-env behaviour regardless of a developer's local `.env`.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_required(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")


def test_loads_with_required_env(monkeypatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.api_token == "test-token"
    assert s.app_db_path == "/tmp/app.db"
    # Defaults
    assert s.model_id == "claude-opus-4-8"
    assert s.constitution_version == "v1"
    # Optional observability stays unset
    assert s.langfuse_public_key is None


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_or_whitespace_required_raises(monkeypatch, blank):
    # A present-but-empty/whitespace secret or DB path must fail fast, not arm
    # the auth boundary with an unusable value (review round-1 #1).
    monkeypatch.setenv("API_TOKEN", blank)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("APP_DB_PATH", blank)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_required_values_are_stripped(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "  test-token  ")
    monkeypatch.setenv("APP_DB_PATH", "  /tmp/app.db  ")
    s = Settings(_env_file=None)
    assert s.api_token == "test-token"
    assert s.app_db_path == "/tmp/app.db"


def test_env_overrides_default(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MODEL_ID", "claude-sonnet-4-6")
    assert Settings(_env_file=None).model_id == "claude-sonnet-4-6"


def test_get_settings_is_cached(monkeypatch):
    _set_required(monkeypatch)
    assert get_settings() is get_settings()
