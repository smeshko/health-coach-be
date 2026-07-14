# TASK-002: Entrypoint seed-on-first-boot + runnable seed-branch shell test

Depends on: TASK-001
Suggested commit: `fix(docker): seed profile.yaml onto the durable volume on first boot`

## Goal

Seed the baked default `profile.yaml` onto `/data/profile.yaml` on first boot when it is
absent, and never touch it when it already exists — via an idempotent, non-root-safe POSIX-`sh`
helper the entrypoint calls before `exec uvicorn`, demonstrated by a runnable both-branches
shell test that needs no Docker daemon.

## Files

- `scripts/seed_profile.sh` (new) — sourceable/runnable POSIX-`sh` helper. Resolves
  `PROFILE_PATH` (default `/data/profile.yaml`) and `SEED_PROFILE` (default `/app/profile.yaml`);
  `mkdir -p "$(dirname "$PROFILE_PATH")"`; `if [ ! -f "$PROFILE_PATH" ]` → `cp "$SEED_PROFILE"
  "$PROFILE_PATH"` with an `echo "[entrypoint] seeding …"`; else `echo "… already present …"`
  (no-op). `set -eu`; safe to run repeatedly and as the unprivileged `app` user.
- `docker-entrypoint.sh` — after `alembic upgrade head` (L22) and **before** `exec uvicorn`
  (L25), call the helper: `sh /app/scripts/seed_profile.sh` (subprocess form keeps the
  entrypoint's `set -eu` intact).
- `scripts/profile_seed_smoke.sh` (new) — the runnable demonstration: sets `SEED_PROFILE` to a
  temp default file and `PROFILE_PATH` to temp targets, runs `seed_profile.sh`, and asserts
  BOTH branches (uses a `check()`-style pass/fail tally like `docker_boot_smoke.sh`). Exits 0
  only if both pass.
- `scripts/docker_boot_smoke.sh` (optional, secondary) — add one assertion after boot: on a
  fresh volume, `/data/profile.yaml` exists and `load_profile()` reads it (in-container python).

## Acceptance

- [ ] Fresh path (no file): after `seed_profile.sh`, `$PROFILE_PATH` exists and is **byte-equal**
      to the baked default (`cmp` clean).
- [ ] Pre-existing path (sentinel content): after `seed_profile.sh`, content is **unchanged**
      (the durable recomputed file is never clobbered) — verified against a sentinel.
- [ ] Helper is idempotent: a second run is a no-op and preserves the (sentinel) file.
- [ ] Runs unprivileged (no root, no `sudo`) and under `set -eu` without error.
- [ ] Entrypoint calls the helper before `exec uvicorn`.

Evidence: `sh scripts/profile_seed_smoke.sh` output showing both PASS lines and exit 0. If the
Docker daemon is available, also paste the `docker_boot_smoke.sh` fresh-volume seed assertion.

## Steps

### RED
- [ ] Write `scripts/profile_seed_smoke.sh` first: temp dir, a fake baked default with known
      content; assert branch A (missing → seeded byte-equal) and branch B (pre-existing sentinel
      → unchanged). Run it — it fails because `seed_profile.sh` doesn't exist yet.

### GREEN
- [ ] Add `scripts/seed_profile.sh` with the `[ ! -f ]` guard + `mkdir -p` + `cp` (as above).
- [ ] Wire `sh /app/scripts/seed_profile.sh` into `docker-entrypoint.sh` after the alembic
      step, before `exec uvicorn`.
- [ ] Re-run `sh scripts/profile_seed_smoke.sh` → both branches PASS, exit 0.

### REFACTOR
- [ ] `chmod +x` the new scripts; confirm shell style consistent with `backup_profile.sh` /
      `docker_boot_smoke.sh`.
- [ ] (Optional) add the fresh-volume seed assertion to `docker_boot_smoke.sh`.

## Notes

- Non-root: entrypoint runs as `USER app`; `/data` is `chown app:app` and `/app/profile.yaml`
  is app-readable, so `cp` into `/data` works without root. The smoke test must run as the
  normal user (no sudo) to mirror this.
- Subprocess form (`sh …/seed_profile.sh`) rather than `.`-sourcing avoids any chance a helper
  `exit`/`set` disturbs the entrypoint's own `set -eu` and `exec` flow.
- Keep the seed step OUT of the alembic/uvicorn happy path failure modes: it should log and
  either succeed or fail loudly (a missing seed **source** is a real image defect worth failing on).
