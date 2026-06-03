"""Typed application settings, loaded and validated from the environment.

`get_settings()` is the single config entry point; `create_app()` invokes it at
startup (E1·P2 wiring) so a missing required variable fails the boot rather than
lazily at first use (ARCHITECTURE §1 — env-driven config, one process).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Required (no sensible default; boot fails if unset) ---
    api_token: str = Field(
        ..., description="Long-lived bearer token gating every authenticated route (E1·P2)."
    )
    app_db_path: str = Field(..., description="Filesystem path to the SQLite app database.")

    # --- LLM / coaching ---
    model_id: str = Field("claude-opus-4-8", description="Default Claude model id for AgentNodes (E9).")
    constitution_version: str = Field("v1", description="Active health-constitution version tag (E3).")

    # --- Observability (optional; wired in E12) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings`, validated against the environment."""
    return Settings()
