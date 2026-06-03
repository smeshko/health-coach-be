"""Typed application settings, loaded and validated from the environment.

`get_settings()` is the single config entry point; `create_app()` invokes it at
startup (E1·P2 wiring) so a missing required variable fails the boot rather than
lazily at first use (ARCHITECTURE §1 — env-driven config, one process).
"""

from functools import lru_cache
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
    constitution_version: str = Field("v1", description="Active health-constitution version tag (E3).")

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


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings`, validated against the environment."""
    return Settings()
