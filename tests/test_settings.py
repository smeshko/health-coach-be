"""Settings load + validation tests (E1·P1 TASK-003).

`_env_file=None` disables `.env` discovery so these assertions exercise pure
process-env behaviour regardless of a developer's local `.env`.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, get_settings

# A realistic api_token: long enough and free of any example/sentinel fragment.
VALID_TOKEN = "test-api-token-0123456789"


@pytest.fixture(autouse=True)
def _clear_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_required(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")


def test_loads_with_required_env(monkeypatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.api_token == VALID_TOKEN
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
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", blank)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_required_values_are_stripped(monkeypatch):
    monkeypatch.setenv("API_TOKEN", f"  {VALID_TOKEN}  ")
    monkeypatch.setenv("APP_DB_PATH", "  /tmp/app.db  ")
    s = Settings(_env_file=None)
    assert s.api_token == VALID_TOKEN
    assert s.app_db_path == "/tmp/app.db"


def test_example_placeholder_token_rejected(monkeypatch):
    # The exact value shipped in .env.example must not boot (review round-2 #1).
    monkeypatch.setenv("API_TOKEN", "replace-me-with-a-long-random-token")
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_short_token_rejected(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "short")
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "bad_path",
    [
        "baseline.db",
        "./baseline.db",
        "/data/baseline.db",
        "health.db",
        "sqlite:///baseline.db",
        # URI scheme/query/fragment forms must not bypass the basename check
        # (review round-4 #1).
        "sqlite:///baseline.db?timeout=30",
        "sqlite:///health.db#frag",
        "sqlite+pysqlite:///baseline.db",
        "file:baseline.db?mode=rwc",
        "file:./health.db",
    ],
)
def test_build_db_path_rejected(monkeypatch, bad_path):
    # baseline.db / health.db are read-only build inputs (review round-3 #1, round-4 #1).
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", bad_path)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("mem_path", [":memory:", "sqlite:///:memory:", "file::memory:?cache=shared"])
def test_in_memory_db_path_rejected(monkeypatch, mem_path):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", mem_path)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_normal_db_path_accepted(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "./app.db")
    assert Settings(_env_file=None).app_db_path == "./app.db"


def test_env_overrides_default(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MODEL_ID", "claude-sonnet-4-6")
    assert Settings(_env_file=None).model_id == "claude-sonnet-4-6"


def test_get_settings_is_cached(monkeypatch):
    _set_required(monkeypatch)
    assert get_settings() is get_settings()
