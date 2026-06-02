# TASK-003: Typed settings module loaded from environment

Depends on: TASK-001
Suggested commit: `feat(core): add typed settings loaded from environment`

## Goal

A `pydantic-settings` config object read from the environment, validated at startup, used everywhere
config is needed.

## Files

- `app/core/settings.py` — `Settings(BaseSettings)` + a cached `get_settings()` accessor
- `tests/test_settings.py` — required-var validation + override behaviour
- `.env.example` — documented variables

## Acceptance

- [ ] `Settings` exposes: `api_token` (required), `app_db_path` (required), `model_id` (default
      `claude-opus-4-8`), `constitution_version`, optional `langfuse_public_key`/`langfuse_secret_key`/
      `langfuse_host`.
- [ ] Missing a required var raises a clear `ValidationError` at load.
- [ ] `get_settings()` is cached (same instance) and reads env via `.env` + process env.
- [ ] `get_settings()` is the single config entry point invoked by `create_app()` at startup (TASK-002),
      so a missing required var fails the boot — not lazily at first use.

## Steps

### RED
- [ ] `tests/test_settings.py`: monkeypatch env → loads; unset required → raises.

### GREEN
- [ ] Implement `Settings` + `get_settings()` (lru_cache); add `.env.example`.

### REFACTOR
- [ ] Group fields by concern; ensure no secret defaults are baked in.

## Notes

Env-driven config matches the deployment model (one container, env config; ARCHITECTURE §1). The
`api_token` here is consumed by E1·P2 auth; `model_id`/`langfuse_*` by E9/E12.
