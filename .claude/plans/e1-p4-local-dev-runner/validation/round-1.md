# Adversarial Validation — Round 1

**Run:** 2026-06-03 04:42 UTC
**Plan:** e1-p4-local-dev-runner
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: the plan documents a first-run path that is known to fail before E2, hard-codes DB deletion against the configured DB-path convention, and has a final validation grep that cannot pass in this repo.

Findings:
- [high] Clean-checkout README flow requires a forward recipe that is not runnable yet (.claude/plans/e1-p4-local-dev-runner/PLAN.md:129-131)
  Verdict: apply. The plan says forward recipes are not expected to fully run until E2/E4, but the acceptance requires the clean-checkout README flow to run `just migrate` before `just run`; under the E1-only scaffold this blocks the documented path before uvicorn can boot, conflicting with E1 acceptance for a clean checkout. Plan files to change: PLAN.md, TASK-003, TASK-004.
  Recommendation: Split README/validation into an E1-current flow (`install`/`env`/`run`) and a future DB flow after E2, or make `migrate` deliberately safe while still proving the future command via `--show`.
- [medium] db-reset ignores the configured app_db_path (.claude/plans/e1-p4-local-dev-runner/tasks/TASK-002-forward-declared-lifecycle-recipes-migrate-seed-bootstrap-db-reset-and-env-handling.md:20-21)
  Verdict: apply. The recipe is specified to delete only hard-coded `app.db*`, while E1/E2 conventions make `settings.app_db_path` the source of truth for Alembic; with `APP_DB_PATH` changed, `db-reset` can delete the wrong local file and leave the actual migrated DB untouched, making stale state look reset. Plan files to change: PLAN.md, TASK-002, TASK-004.
  Recommendation: Either enforce `APP_DB_PATH=app.db` for local dev and fail if it differs, or resolve the configured path and delete that DB plus WAL/SHM with explicit guards against empty paths, parent traversal, and `baseline.db`.
- [medium] Final litestream validation is repo-wide and will fail on existing docs (.claude/plans/e1-p4-local-dev-runner/tasks/TASK-004-final-validation.md:47-51)
  Verdict: apply. TASK-004 asks `grep -riE "litestream" .` to show none introduced, but existing architecture/epic docs already mention litestream and this plan itself mentions it, so the validation is a false blocker or will train implementers to ignore a failing check. Plan files to change: TASK-004, PLAN.md risk text if kept.
  Recommendation: Scope the check to files introduced or changed by this phase: no Docker/compose/litestream files in `git status`, no docker/litestream references in `justfile`, and only the allowed negative Docker note in the README section.

Next steps:
- Revise the plan before implementation; these are plan-level blockers, not missing-source defects.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Clean-checkout README flow runs `just migrate` (E2) before `just run`, blocking first boot on the E1-only scaffold | high | apply | Real coherence defect: the documented first-run path can't complete pre-E2, conflicting with "uvicorn boots from a clean checkout". Split into an E1-now flow vs a post-E2 DB flow. | PLAN.md:Scope/AC, TASK-003, TASK-004 |
| 2 | `db-reset` hard-codes `app.db*`, ignoring `settings.app_db_path` (source of truth per E1·P1/E2·P1) | med | apply | Valid: if `APP_DB_PATH` differs, the recipe deletes the wrong file and leaves the real DB. Default stays `app.db` but the plan must address the non-default case with safety guards. | PLAN.md:Decisions/Risks, TASK-002, TASK-004 |
| 3 | Final-validation `grep -riE "litestream" .` is repo-wide; existing docs already mention litestream so it can never pass | med | apply | Correct: the check is a false blocker. Scope it to files this phase introduces/changes (justfile, README section, git status), not the whole repo. | TASK-004, PLAN.md:Risks |
