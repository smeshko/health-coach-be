"""Typed application settings, loaded and validated from the environment.

`get_settings()` is the single config entry point; `create_app()` invokes it at
startup (E1·P2 wiring) so a missing required variable fails the boot rather than
lazily at first use (ARCHITECTURE §1 — env-driven config, one process).
"""

import re
from functools import lru_cache
from pathlib import PurePath
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Required string that is stripped and must be non-empty, so a blank or
# whitespace-only value fails fast at startup rather than silently arming the
# auth boundary / DB path with an unusable value.
RequiredStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# The api_token is the sole auth secret (E1·P2 compares requests against it), so
# it must be a real secret — not a short string and not a copied example value.
_MIN_API_TOKEN_LEN = 16
_SENTINEL_TOKEN_FRAGMENTS = (
    "replace-me",
    "change-me",
    "changeme",
    "your-token",
    "example",
    "placeholder",
)

# baseline.db / health.db are read-only *build inputs*, never opened at runtime
# (ARCHITECTURE §1; DB.md). Runtime + Alembic (E2) route through app_db_path, so
# pointing it at one of these — or at a non-durable in-memory database — would
# silently corrupt the build corpus or lose state. Reject both at startup.
_FORBIDDEN_DB_BASENAMES = frozenset({"baseline.db", "health.db"})
# Leading URL scheme (`sqlite://`, `sqlite+pysqlite://`, `file:`); stripped before
# resolving the basename so URI forms can't smuggle a forbidden name past the check.
_DB_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:(//)?")


def _db_target_basename(value: str) -> str:
    """Resolve the target filename of a db path/URI, ignoring scheme + query/fragment."""
    candidate = value.split("?", 1)[0].split("#", 1)[0]
    candidate = _DB_SCHEME_RE.sub("", candidate)
    return PurePath(candidate).name.lower()


class Settings(BaseSettings):
    """Process configuration sourced from the environment (and an optional `.env`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # `model_id` lives in pydantic's protected `model_` namespace; opt out of
        # the protection so the field name stays as the domain calls it.
        protected_namespaces=(),
    )

    # --- Required (no sensible default, must be non-empty; boot fails otherwise) ---
    api_token: RequiredStr = Field(
        ..., description="Long-lived bearer token gating every authenticated route (E1·P2)."
    )
    app_db_path: RequiredStr = Field(..., description="Filesystem path to the SQLite app database.")

    # --- LLM / coaching ---
    model_id: str = Field("claude-opus-4-8", description="Default Claude model id for AgentNodes (E9).")
    # The Anthropic API key for the PydanticAI agent (E9). Optional so non-LLM
    # entrypoints boot without it (tests override the model; /sync and /health need
    # no key). pydantic-settings loads it from .env / a real env var into THIS field
    # but does not export it to os.environ, where pydantic-ai's AnthropicProvider
    # reads it — the uvicorn entrypoint (app/main.py) bridges that gap at startup.
    anthropic_api_key: str | None = Field(
        None, description="Anthropic API key for the LLM agent (E9); env ANTHROPIC_API_KEY."
    )
    constitution_version: str = Field("v1", description="Active health-constitution version tag (E3).")
    # Optional override for the profile.yaml location (E3·P1). Defaults (when
    # unset) to the repo-root file resolved in `app/core/profile.py`. A deployed
    # runtime whose profile.yaml is not at the source-tree root sets PROFILE_PATH
    # to point the loader at the real file. Read as a bare env var by the loader
    # so loading constants never requires the auth-bearing Settings; this field
    # is the typed mirror of that same env var.
    profile_path: str | None = Field(
        None, description="Override filesystem path to profile.yaml (E3·P1); env PROFILE_PATH."
    )

    # --- Observability (optional; wired in E12) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    @field_validator("api_token")
    @classmethod
    def _reject_weak_or_example_token(cls, value: str) -> str:
        # `value` is already stripped + non-empty via RequiredStr.
        if len(value) < _MIN_API_TOKEN_LEN:
            raise ValueError(f"api_token must be at least {_MIN_API_TOKEN_LEN} characters")
        lowered = value.lower()
        if any(fragment in lowered for fragment in _SENTINEL_TOKEN_FRAGMENTS):
            raise ValueError(
                "api_token looks like a placeholder/example value — set a real secret "
                "(a copied .env.example must not boot)"
            )
        return value

    @field_validator("app_db_path")
    @classmethod
    def _reject_unsafe_db_path(cls, value: str) -> str:
        # `value` is already stripped + non-empty via RequiredStr.
        lowered = value.lower()
        # In-memory SQLite is non-durable; runtime state must persist to a file.
        if ":memory:" in lowered or "mode=memory" in lowered:
            raise ValueError(
                "app_db_path must be a durable file path, not an in-memory SQLite database"
            )
        # baseline.db / health.db are read-only build inputs, never opened at runtime.
        # Normalize scheme + query/fragment first so SQLite URI variants can't bypass it.
        basename = _db_target_basename(value)
        if basename in _FORBIDDEN_DB_BASENAMES:
            raise ValueError(
                f"app_db_path must not target the read-only build database ({basename}); "
                "use a runtime path such as ./app.db"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings`, validated against the environment."""
    return Settings()
