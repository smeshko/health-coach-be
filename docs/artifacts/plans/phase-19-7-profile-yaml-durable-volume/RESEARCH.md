# Research: profile.yaml durability across redeploys (Phase 19.7)

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `app/core/profile.py` — the `profile.yaml` loader **and** the single writer.
  - L30 `PROFILE_PATH = Path(__file__).resolve().parents[2] / "profile.yaml"` — the
    source-tree anchor (repo/image root).
  - L33-59 `_ProfilePathSettings` + `_default_profile_path()` — reads a `PROFILE_PATH`
    override from **process env and `.env`**, else falls back to the anchor.
  - L286-304 `load_profile(path=None)` — `path=None` → `_default_profile_path()`.
  - L307-336 `write_profile(profile, *, path=None)` — `path=None` → the **same**
    `_default_profile_path()` (L323); atomic temp-file + `fsync` + `os.replace` into
    `target.parent`. **This is the recompute writer, and it honors the override.**
- `tests/core/test_profile.py` — the override is **already regression-covered**, so TASK-003
  is an incremental hardening, not net-new coverage:
  - L472 `test_profile_path_env_override_is_honored` — no-arg `load_profile()` honors the env override.
  - L513 `test_profile_path_dotenv_override_is_honored` — `.env`-only override honored (parity).
  - L489 `test_settings_exposes_profile_path_override` — `Settings.profile_path` mirror (uses `/data/profile.yaml`).
  - **L621 `test_write_profile_default_path_honours_env_override`** — no-arg `write_profile()` lands at
    the env path AND no-arg `load_profile()` reads it back (a write+load round-trip). This already locks
    the writer-honors-override assumption; it asserts `constitution_version` only (not full-`Profile`
    equality) and does not assert the source-tree anchor was left unwritten — the two deltas TASK-003 adds.
- `app/core/settings.py` L81-86 — `Settings.profile_path` mirrors the same `PROFILE_PATH`
  env knob (confirmed present).
- `app/core/weekly_planner.py` L786-865 `PersistPlanNode` — stages the proposed rewrite under
  `PENDING_PROFILE_WRITE_KEY` (does NOT write the file itself).
- `app/api/routes/weekly.py` L64-70 `_write_profile_with_retry(pending)` → `write_profile(pending)`
  (no path arg) — the post-commit apply. Confirms the write routes through the override.
- `Dockerfile` — L42 `COPY alembic.ini profile.yaml README.md ./` (bakes `/app/profile.yaml`);
  L55-62 `mkdir -p /data`, `chown -R app:app /app /data`, `VOLUME ["/data"]`,
  `ENV APP_DB_PATH=/data/app.db … HOME=/app`; L70 `USER app`; L74 `ENTRYPOINT`.
- `docker-entrypoint.sh` — POSIX `sh`, `set -eu`; `alembic upgrade head` then `exec uvicorn`.
- `RUNBOOK.md` §5 (L152-170) — "Known limitation: profile.yaml durability (Phase 19.5)";
  already names the exact fix ("move PROFILE_PATH onto /data with entrypoint logic to seed").
- `scripts/backup_profile.sh` + `deploy/launchd/com.coachapp.profile-backup.plist` — the
  6-hourly YAML backup (litestream covers only SQLite). Defense-in-depth; stays.
- `scripts/docker_boot_smoke.sh` — existing bash smoke-test pattern (`check()` helper,
  tmp volume, tear-down). Template for the demonstration test style.
- `.env.docker.example` L28-29 — already carries a commented `# PROFILE_PATH=/data/profile.yaml`
  and a now-stale comment "PROFILE_PATH defaults to the image's /app/profile.yaml".

## Architecture Facts

- The `PROFILE_PATH` override seam is fully wired on the Python side; loader and writer share
  `_default_profile_path()`. Setting the env var moves BOTH read and write to `/data` — the
  fix is Docker/entrypoint + env, not new Python resolution logic.
- Post-commit write flow is already hardened (Phase 19.5): a failed write invalidates the
  committed plan so a cache hit can't serve diverged constants. The ONLY residual gap is
  redeploy reverting a *successful* write because the file was on the ephemeral `/app` layer.
- `/data` is app-owned and a `VOLUME`; `app.db` already lives there durably via `APP_DB_PATH`.
- Entrypoint runs unprivileged (`USER app`), so seed `cp` and `write_profile`'s mkstemp in
  `/data` both work without root.

## Constraints

- POSIX `sh` (not bash) for `docker-entrypoint.sh` / `seed_profile.sh`; `set -eu`.
- Seed must be idempotent (never clobber an existing `/data/profile.yaml`) and non-root-safe.
- Done-means-demonstrated: no live deploy — demonstrate at shell + pytest level.
- Global rule: never decompose behavior in a way that leaves it unverified; each task = one commit.

## Useful Commands

```bash
# from the worktree root
uv run pytest tests/core/test_profile.py -q       # regression round-trip (TASK-003)
sh scripts/profile_seed_smoke.sh                  # seed both-branches demo (TASK-002), no docker
uv run pytest -q                                  # full suite (TASK-005)
uv run ruff check                                 # lint (TASK-005)
bash scripts/docker_boot_smoke.sh                 # optional: fresh-volume seed assertion (needs docker)
```

## Existing coverage (validation round-1 #1)

- The writer-honors-override round-trip TASK-003 targets **already exists** at
  `tests/core/test_profile.py::test_write_profile_default_path_honours_env_override` (L621), and the
  loader half at L472. TASK-003 is therefore a narrow *strengthening* of L621 (full-`Profile` equality +
  assert the source-tree anchor was NOT written), not a from-scratch regression test. Do not add a
  duplicate; extend/replace the L621 assertions in place.

## Uncertainty

- First-redeploy stale-default seed (see PLAN Risks) — resolved as a documented one-time
  cutover step in RUNBOOK, not a code concern; the app's own `?refresh=true` re-writes current
  constants and the profile-backup snapshot is the fallback.
- Whether to also add a docker-level redeploy-survival assertion: kept optional/secondary
  because it needs a daemon and a write-trigger; the shell + pytest demos are the primary gate.

## References

- iOS epic (different repo): `docs/artifacts/epics/19-trustworthy-numbers.md` §19.7.
- `RUNBOOK.md` §5; `RELEASE-READINESS-TODO.md` (profile-backup references).
