# Adversarial Review — Round 1

**Run:** 2026-07-14 05:48 UTC
**Branch:** fix/phase-19-7-profile-yaml-durable-volume
**Base:** origin/staging
**Commits reviewed:** 34debd3..073f852
**Reviewer:** subagent (Codex usage-limited — reset Jul 20; fell back to a clean general-purpose subagent with the same adversarial framing per the shared protocol)

## Codex output

<!-- Reviewer was a general-purpose subagent (Codex unavailable). Output pasted verbatim below. -->

Both demonstrations pass. I have traced the full chain. Here are my findings.

## Findings

**1. Seed `cp` is not atomic, and the `[ ! -f ]` guard then blocks self-heal — a partial file survives forever**
Severity: **medium** · `scripts/seed_profile.sh:24`
- Scenario: fresh `/data` volume, first boot. The entrypoint runs `cp "$SEED_PROFILE" "$PROFILE_PATH"` (plain, non-atomic). If the container is SIGKILLed / OOM-killed / deploy-timed-out mid-copy, `/data/profile.yaml` is left truncated. On the next boot the guard `[ ! -f "$PROFILE_PATH" ]` is now **false** (the partial file exists), so seed is skipped, and the corrupt file is never re-seeded. `load_profile()` is lazy (called at request time in `weekly_planner.py`/`daily_adjuster.py`, not at boot — confirmed no boot-time load), so the container starts "healthy" and then 500s on the first weekly/daily request with a YAML `ValueError`/`ValidationError`, with no self-heal path.
- Reasoning: `write_profile()` goes to great lengths to be atomic (mkstemp + fsync + `os.replace`), but the seed that this whole fix relies on does a bare `cp`. The window is tiny (774-byte file, first boot only), but it directly undercuts the durability claim and the guard design makes it permanent once it happens. A `cp` to a temp name in the same dir + `mv` would close it, mirroring `write_profile`.

**2. RUNBOOK cutover mitigation command `docker cp <container>:/app/profile.yaml -` does not place the file at `/data/profile.yaml`**
Severity: **medium** · `RUNBOOK.md:176-178`
- The `-` target streams a **tar archive to stdout**; it does not write anything to `/data/profile.yaml`. As written, "`docker cp <container>:/app/profile.yaml -` … → `/data/profile.yaml`" is not a runnable copy-into-the-volume step. To actually pre-seed the durable volume you need either `docker cp <container>:/app/profile.yaml ./profile.yaml` followed by `docker cp ./profile.yaml <newcontainer>:/data/profile.yaml`, or a copy directly into the mounted volume.
- Reasoning: this is the sole actionable mitigation for the honestly-documented one-time stale-seed risk, so a wrong command means an operator following it verbatim gets a tar dump to their terminal and no cutover. The prose intent is right; the command is incorrect/incomplete.

**3. Bind-mounted `/data` (not a named volume) makes the seed `cp` abort the boot under `set -eu`**
Severity: **low** (informational) · `scripts/seed_profile.sh:20-24`
- A **named** volume inherits the image's `chown app:app /data`, so the unprivileged `cp` works (verified in Dockerfile). A **bind mount** from the host keeps the host uid/gid; if that isn't `app`-writable, `cp` fails, `set -e` aborts, and the container never starts. This is fail-loud rather than silent corruption (acceptable), but it's undocumented and differs from the "non-root-safe" claim in the script header, which only holds for the named-volume case.

## Confirmed fine (traced, not problems)

- **Env inheritance (scrutiny #1c):** `ENV PROFILE_PATH=/data/profile.yaml` is a container-level var in `/proc/1/environ`, inherited by the `sh /app/scripts/seed_profile.sh` subprocess; and the script independently defaults to the same value (`${PROFILE_PATH:-/data/profile.yaml}`). No gap.
- **No clobber / no-op exits 0 (scrutiny #1a,b):** `[ ! -f ]` guard is correct; pre-existing file is left untouched and exits 0. Demonstrated by `profile_seed_smoke.sh` (7/7 pass, including idempotent re-run).
- **Writer honors the override (scrutiny #3):** `weekly.py:70` `_write_profile_with_retry` → `write_profile(pending)` with no path arg → `write_profile` resolves via the same `_default_profile_path()` as `load_profile`. Runtime writes land on `/data`. Working as intended.
- **Ordering / race (scrutiny #5):** entrypoint is sequential — `alembic upgrade` → `sh seed_profile.sh` → `exec uvicorn`. The seed completes before uvicorn is exec'd, so no window where a request/recompute runs before seed. The 6-hourly backup job overlapping the sub-second first-boot copy is negligible and only feeds defense-in-depth. Fine.
- **Test strength / not vacuous (scrutiny #6):** `test_write_profile_default_path_honours_env_override` asserts `target.is_file()` (a writer that ignored the override would write the anchor and fail this), full `load_profile() == original`, plus anchor byte-equality **and** `st_mtime_ns` equality. Can't pass vacuously. Demonstrated green.
- **Byte-equal loadable seed (scrutiny #2):** baked `/app/profile.yaml` is `COPY`'d in the image and loads (`constitution_version: v1` confirmed); `cp` is byte-exact, so the smoke `cmp` and the boot-smoke `load_profile()` assertion are meaningful.
- **RUNBOOK §5 honesty (scrutiny #4):** the "One-time cutover" note honestly documents the stale-baked-default first-redeploy risk and retains the backup job as defense-in-depth. Only the `docker cp` command mechanics (finding #2) are off; the framing does not over-claim.

No mismatch between PLAN decisions and the code otherwise.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Seed `cp` non-atomic; `[ ! -f ]` guard blocks self-heal → truncated seed survives forever, 500s at request time | med | fix | Real durability hole in a durability phase; `write_profile` is atomic but the seed it relies on is not. Fix (mktemp same-dir + `mv`) mirrors the writer and makes a partial seed self-heal on next boot. | 688b6d7 |
| 2 | RUNBOOK cutover command `docker cp …:/app/profile.yaml -` streams a tar to stdout, never lands at `/data/profile.yaml` | med | fix | The sole actionable mitigation for the documented one-time stale-seed risk is not runnable as written; operator gets a tar dump. Doc-only correctness fix. | cdbb17f |
| 3 | Bind-mounted `/data` (non-named volume) with non-`app` uid makes seed `cp` abort boot under `set -eu` | low | reject | Fail-loud, not silent corruption (acceptable). The documented/only deployment is a **named** volume (`VOLUME ["/data"]` + `-v <vol>:/data`), which inherits the image's `chown app:app`, so the "non-root-safe" header holds for the shipped topology. Bind-mount with a mismatched host uid is an unsupported deployment, out of scope for this phase. | |
