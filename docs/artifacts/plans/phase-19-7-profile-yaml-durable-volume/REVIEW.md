# Review Summary — phase-19-7-profile-yaml-durable-volume

**Rounds:** 2
**Fix commits:** 688b6d7..cdbb17f
**Reviewer:** general-purpose subagent both rounds (Codex usage-limited until Jul 20 — documented Codex-unavailable fallback).

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 3        | 2     | 0        | 1        |
| 2     | 4        | 0     | 1        | 3        |

## Fixes

### Round 1
- `688b6d7` — seed `profile.yaml` atomically via same-dir temp + `mv` (mirrors `write_profile`'s mkstemp+`os.replace`) so an interrupted first-boot copy self-heals instead of leaving a truncated file the `[ ! -f ]` guard would permanently skip (round-1 #1)
- `cdbb17f` — fix RUNBOOK cutover command: the sole stale-seed mitigation used `docker cp …:/app/profile.yaml -` (streams a tar to stdout, never lands the file); replaced with a runnable two-step `docker cp` (pull to host, push onto the durable volume) (round-1 #2)

## Deferred

- (round-2 #2) RUNBOOK cutover has a boot→operator-`cp` window where a recompute could be overwritten — negligible for this single-operator self-hosted deploy and the doc already offers the safer `?refresh=true` alternative; a one-line "do this before serving traffic" doc nicety could be added later. (Linear: none — captured here only.)

## Rejected

- (round-1 #3 / round-2 #3) Bind-mounted `/data` with a non-`app` host uid makes the seed `cp` abort the boot under `set -eu` — fail-loud not silent corruption, and the shipped/only topology is a **named** volume (`VOLUME ["/data"]` + image `chown app:app /data`) which is app-writable; bind-mount-with-mismatched-uid is an unsupported deployment. Round 2 independently agreed the reject is defensible.
- (round-2 #1) Stray truncated `.seed.XXXXXX` temp can leak on an untrappable SIGKILL between `cp` and `mv` — cosmetic only: `PROFILE_PATH` self-heals and nothing on `/data` is globbed/consumed (`backup_profile.sh` copies the exact path, litestream is SQLite-only). Not worth added complexity to close an untrappable-signal window.
- (round-2 #4) Interrupted-seed → re-seed self-heal path is not unit-tested — acceptable: the atomic design means a partial seed never lands at `PROFILE_PATH`, so self-heal reduces to the already-covered fresh-path branch, and simulating a mid-`cp` kill in a shell test is impractical for negligible value.

## Scrutiny notes (task-directed checks, all confirmed clean)

- **Seed clobber / boot safety:** the `[ ! -f "$PROFILE_PATH" ]` guard never overwrites an existing recomputed file; the no-op path exits 0; a missing seed *source* fails loud (real image defect). `PROFILE_PATH` is a Dockerfile `ENV` (in `/proc/1/environ`), inherited by the `sh /app/scripts/seed_profile.sh` subprocess, and the script also self-defaults to `/data/profile.yaml`. After fix #1 the copy is atomic, so an interrupted seed cannot leave a corrupt file at the target.
- **Single-knob correctness:** `_write_profile_with_retry` → `write_profile(pending)` (no path arg) → `_default_profile_path()` → `_ProfilePathSettings.profile_path` (`PROFILE_PATH`). The runtime writer resolves to `/data/profile.yaml`, same as the loader. The fix is not silently bypassed.
- **Byte-equal loadable seed:** baked `/app/profile.yaml` is `COPY`'d into the image and loads (`constitution_version: v1`); `cp` is byte-exact, so the smoke `cmp` and the boot-smoke `load_profile()` assertions are meaningful.
- **RUNBOOK §5 accuracy:** does not over-claim — the one-time first-redeploy stale-seed risk is honestly documented with a now-runnable cutover mitigation and retains the profile-backup job as defense-in-depth.
- **No demo/scratch leakage:** `git ls-files` shows no `test_red_demo.py` or other temporary demo file on the branch; demonstration is via the committed `scripts/profile_seed_smoke.sh` (7/7) and the strengthened `tests/core/test_profile.py` round-trip only.
- **`_clear_profile_path_env`:** a legit `@pytest.fixture(autouse=True)` (Pyright false-positive "unused"), not dead code.
