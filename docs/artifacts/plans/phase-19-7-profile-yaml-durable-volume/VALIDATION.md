# Validation Summary — phase-19-7-profile-yaml-durable-volume

**Rounds:** 2
**Plan status at validation:** draft
**Run on:** 2026-07-14

> Reviewer: general-purpose subagent both rounds (Codex-unavailable fallback — the backend
> `docs/` dir is gitignored, so `codex-local:adversarial-review --scope working-tree` sees no
> diff to review). Same adversarial framing, recorded identically per the shared protocol.

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 5        | 3       | 0        | 2 (affirm) |
| 2     | 3        | 1       | 0        | 2 (affirm) |

All load-bearing claims the task flagged were verified true against current code and needed no
correction: single-knob sufficiency (both `load_profile()`/`write_profile()` resolve through
`_default_profile_path()`, `app/core/profile.py` L295/L323; `_write_profile_with_retry` calls
`write_profile(pending)` with no path, `weekly.py` L70); seed idempotency + non-root safety
(`USER app`, `/data` chowned, `[ ! -f ]` guard safe under `set -eu`); first-boot/cutover
correctness (fresh volume seeded with the committed, loadable default; cutover RUNBOOK mitigation
actionable); PROFILE_PATH env→process-env parity (`_ProfilePathSettings` reads process env + `.env`).

## Applied

### Round 1
- `RESEARCH.md` + `PLAN.md` (Scope, Research Summary, Risks) + `tasks/TASK-003` — the writer-honors-override
  write+load round-trip TASK-003 targeted **already exists** at `tests/core/test_profile.py::test_write_profile_default_path_honours_env_override`
  (L621); loader half at L472. Reframed the plan from "add a regression test" to "strengthen the existing
  L621 test" (full-`Profile` equality + assert the source-tree anchor was NOT written), and cited the
  existing coverage in RESEARCH so the implementer doesn't add a duplicate. (round-1 #1)
- `tasks/TASK-005` — added a no-Docker-daemon step proving AC #1: grep the Dockerfile for the durable
  `PROFILE_PATH=/data/profile.yaml` env line and the retained baked `COPY … profile.yaml` seed source. (round-1 #2)
- `tasks/TASK-005` — added an explicit AC #4 step: `git diff RUNBOOK.md .env.docker.example` proving the
  §5 "Resolved (Phase 19.7)" retitle + cutover note + corrected env comment (previously only implied by
  the catch-all bullet). (round-1 #3)

### Round 2
- `tasks/TASK-005` — clarified the AC #1 grep step's prose: the matched line is a continuation of the
  multi-line `ENV` block (no literal `ENV` token), not "the ENV line". (round-2 #1)

## Deferred

- None.

## Rejected

- (round-1 #4) One-time first-redeploy stale-default seed risk — **affirm, not a defect.** The `[ ! -f ]`
  guard no-ops on a pre-placed `/data/profile.yaml`, and the `?refresh=true` fallback re-writes current
  constants; the cutover mitigation is correctly homed in TASK-004's RUNBOOK note. Reviewer confirmed
  actionable in both rounds.
- (round-1 #5) Seed step safety under `set -eu` + non-root — **affirm, not a defect.** `mkdir -p`/`[ ! -f ]`/`cp`
  are `set -eu`-safe; the subprocess `sh scripts/seed_profile.sh` form isolates the entrypoint's `set -eu`/`exec`;
  `cp` into app-owned `/data` needs no root; a missing seed source fails loudly by design. Confirmed against
  `docker-entrypoint.sh` (L13 `set -eu`, alembic L22, seed before `exec` L25).
