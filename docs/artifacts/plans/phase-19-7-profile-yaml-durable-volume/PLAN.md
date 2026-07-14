# Plan: profile.yaml durability across redeploys (Phase 19.7)

Status: in-progress
Branch: fix/phase-19-7-profile-yaml-durable-volume
Risk: medium
Epic: 19 — Make the numbers trustworthy (audit wave 2, tracked in the iOS repo's docs/artifacts/epics/19-trustworthy-numbers.md)
Phase: 19.7 — profile.yaml durability across redeploys
Linear: none
Created: 2026-07-14

## Goal

Make a recomputed `profile.yaml` survive a container redeploy by moving the runtime
constants file onto the durable `/data` volume (alongside `app.db`), with entrypoint
logic that seeds the image's baked default onto a fresh/empty volume only when the
durable file is absent — never clobbering an existing recomputed file. This closes the
residual "Redeploy can still lose a successful write" hardening deferred from Phase 19.5.

## Scope

- **`Dockerfile`** — add `ENV PROFILE_PATH=/data/profile.yaml` alongside the existing
  `ENV APP_DB_PATH=/data/app.db` (Dockerfile L61), so the runtime loader **and** writer
  resolve the constants file on the durable volume. Keep the baked `COPY … profile.yaml …`
  (L42) — the `/app/profile.yaml` layer stays as the **seed source** (and the source-tree
  anchor for any non-container `uv run`).
- **`docker-entrypoint.sh` + a new `scripts/seed_profile.sh`** — extract an idempotent,
  non-root-safe seed step into a sourceable POSIX-`sh` helper the entrypoint calls before
  `exec uvicorn`: if `$PROFILE_PATH` is absent, `cp` the baked default into place; if it
  already exists on the volume, leave it untouched. A dedicated runnable shell test
  (`scripts/profile_seed_smoke.sh`) exercises **both** branches (fresh dir → seeded and
  byte-equal to the default; pre-existing sentinel → unchanged) with no Docker daemon.
- **Regression test** (`tests/core/test_profile.py`) — the write+load round-trip under a
  `PROFILE_PATH` override **already exists** (`test_write_profile_default_path_honours_env_override`,
  L621; loader half at L472). This phase *strengthens* that existing test — add full-`Profile`
  equality on the round-trip and an assertion that the source-tree anchor was NOT written — rather
  than adding a duplicate, locking in that the recompute writer honors the override the fix relies on.
- **Docs** — `RUNBOOK.md` §5 "Known limitation" → "Resolved (Phase 19.7)"; refresh the
  stale `.env.docker.example` comment (`# PROFILE_PATH defaults to the image's /app/…`).

## Out of Scope

- Any change to Python path-resolution logic — the `PROFILE_PATH` override seam already
  exists in `app/core/profile.py` (`_default_profile_path`) and `app/core/settings.py`
  (`Settings.profile_path`), and the writer already routes through it. This phase adds no
  new resolver code.
- litestream / `com.coachapp.profile-backup` mechanics — the 6-hourly YAML backup job stays
  as defense-in-depth; it is not being removed or reworked.
- Live production deploy / device validation — the epic marks these "Implemented — device
  validation pending"; demonstration here is at the shell + pytest level (done-means-
  demonstrated without a live deploy).

## Research Summary

The override seam is already fully wired on the Python side, so this phase is almost
entirely Docker + entrypoint. See `RESEARCH.md` for the verified call chain. Headline
finding: **the recompute writer already honors `PROFILE_PATH`** — `write_profile()`
(`app/core/profile.py` L323) resolves through the *same* `_default_profile_path()` as
`load_profile()`, and the endpoint (`app/api/routes/weekly.py` `_write_profile_with_retry`,
L64-70) calls `write_profile(pending)` with **no path arg**. So setting the env var lands
both read and write on `/data`; no writer code change is needed. The writer-honors-override
round-trip is **already regression-covered** (`test_write_profile_default_path_honours_env_override`,
L621; loader override at L472), so TASK-003 only *strengthens* that existing test, it does not
add net-new coverage. No test hardcodes `/app/profile.yaml`.

## Decisions

- **Set the default via `ENV PROFILE_PATH` in the image, not a resolver code change** — the
  override already reads process env (`_ProfilePathSettings` / `Settings.profile_path`), so
  a Dockerfile `ENV` is the minimal, config-driven lever (parity with how `APP_DB_PATH`
  already points `app.db` at `/data`). No Python change to loader/writer resolution.
- **Keep the baked file at `/app/profile.yaml` as the seed source** (do not rename to
  `profile.default.yaml`) — it is *also* the source-tree anchor `_default_profile_path()`
  falls back to, so keeping the name preserves that semantic for non-container `uv run`
  inside the image, and is non-breaking. In-container the `ENV` override wins, so `/app`'s
  copy is only ever read as the seed.
- **Factor the seed into `scripts/seed_profile.sh`, sourced by the entrypoint** — makes the
  seed logic directly runnable/testable off a Docker daemon (the demonstration), mirrors the
  existing `scripts/*.sh` convention (`docker_boot_smoke.sh`, `backup_profile.sh`), and keeps
  `docker-entrypoint.sh` thin. The Dockerfile already `COPY scripts ./scripts`, so it ships.
- **Idempotent `[ ! -f "$PROFILE_PATH" ]` guard** — the seed is a no-op whenever the durable
  file exists, so a redeploy never overwrites a recomputed file; a fresh/empty volume always
  gets a valid constants file. `mkdir -p "$(dirname "$PROFILE_PATH")"` for robustness.
- **Demonstration = shell seed-branch test + pytest override round-trip** (both runnable on
  the dev laptop, no live deploy) — satisfies done-means-demonstrated. The Docker
  `docker_boot_smoke.sh` gets an optional secondary assertion (fresh volume → `/data/
  profile.yaml` seeded and loadable) but is not the primary gate since it needs a daemon.

## Risks

- **One-time first-redeploy seed of a possibly-stale default.** An existing prod `/data`
  volume has no `/data/profile.yaml` yet (today it lives at `/app`). On the first redeploy
  after 19.7 ships, the seed branch fires and writes the *baked* default to `/data`, which
  could be older than the `/app` file recompute had been rewriting under the old behavior —
  the same one-time loss the current limitation already risks on every redeploy, but now the
  **last** time it can happen. Mitigation (RUNBOOK cutover note in TASK-004): before/at the
  19.7 cutover, copy the live `/app/profile.yaml` (or the latest `com.coachapp.profile-backup`
  snapshot) into `/data/profile.yaml`, or run one `?refresh=true` weekly right after to
  re-stage + re-write current constants.
- **Non-root / ownership.** The entrypoint runs as `USER app`; `/data` is `chown app:app`
  and `/app/profile.yaml` is app-readable, so the `cp` and later atomic writes
  (`write_profile` mkstemp in `target.parent` = `/data`) succeed without root. Verified in
  the Dockerfile; asserted by the shell test running unprivileged.
- **Writer silently NOT honoring the override (hypothetical regression).** Guarded by the
  existing L621 round-trip test, strengthened in TASK-003 (full-`Profile` equality + anchor
  not written), so a future refactor that bypasses `_default_profile_path()` fails loudly.

## Acceptance Criteria

- [ ] A redeploy no longer reverts a recomputed `profile.yaml`: the runtime file lives on the
      durable `/data` volume (`ENV PROFILE_PATH=/data/profile.yaml`), and the entrypoint seeds
      the baked default only when `/data/profile.yaml` is absent.
- [ ] `scripts/seed_profile.sh` is idempotent and non-root-safe: fresh path → seeded byte-equal
      to the baked default; pre-existing path → left untouched. Demonstrated by
      `scripts/profile_seed_smoke.sh` exiting 0 (both branches asserted).
- [ ] With `PROFILE_PATH` set, both no-arg `load_profile()` and no-arg `write_profile()` resolve
      to the env path (round-trip test green in `uv run pytest`).
- [ ] `RUNBOOK.md` §5 reads "Resolved (Phase 19.7)" describing seed-on-boot + durable path;
      `.env.docker.example` comment reflects the `/data/profile.yaml` default; the profile-backup
      note is retained as still-true defense-in-depth.
- [ ] `uv run pytest` and `uv run ruff check` both green.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Dockerfile: default PROFILE_PATH to /data/profile.yaml, keep baked seed source
- [x] TASK-002: Entrypoint seed-on-first-boot + runnable seed-branch shell test
- [ ] TASK-003: Regression test: loader AND recompute writer both honor PROFILE_PATH override
- [ ] TASK-004: RUNBOOK §5 + .env.docker.example: Known limitation -> Resolved (Phase 19.7)
- [ ] TASK-005: Final Validation
