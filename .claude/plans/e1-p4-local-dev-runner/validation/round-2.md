# Adversarial Validation — Round 2

**Run:** 2026-06-03 04:48 UTC
**Plan:** e1-p4-local-dev-runner
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: round-1 README and Docker/litestream fixes are addressed, but the db-reset fix is still not operationally safe enough to implement from the plan.

Findings:
- [medium] db-reset can pass validation while not resetting the configured DB safely (.claude/plans/e1-p4-local-dev-runner/tasks/TASK-002-forward-declared-lifecycle-recipes-migrate-seed-bootstrap-db-reset-and-env-handling.md:20-21)
  Verdict: apply. Rationale: the task specifies `DB="${APP_DB_PATH:-app.db}"`, guard, then `rm`, but does not require those commands to run in one shell block/shebang; `just` runs separate recipe lines independently, so a natural multi-line implementation loses `DB` before the guard/removal while `just --show`/grep validation still passes. Also, `${APP_DB_PATH:-app.db}` turns an explicitly empty `APP_DB_PATH` into `app.db`, making the promised empty-path refusal unreachable. Impact: `db-reset` can fail or target the fallback DB while appearing validated, leaving stale configured DB state or deleting the wrong local file. Plan files to change: PLAN.md, TASK-002, TASK-004.
  Recommendation: Specify `db-reset` as a single shell block or shebang recipe, distinguish unset vs empty (`${APP_DB_PATH-app.db}` plus an explicit empty check, or equivalent), use `rm -f --`, and add final-validation behavior checks for empty `APP_DB_PATH` and the configured DB path before the migrate step fails.

Next steps:
- Revise db-reset implementation instructions and validation before shipping this plan.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `db-reset` must run as a single shell block (just runs each recipe line in its own process, so `DB=…` would not survive to the guard/`rm`); `${APP_DB_PATH:-app.db}` collapses explicit-empty to `app.db` defeating the empty-path refusal; use `rm -f --` | med | apply | Correct and sharp — the round-1 #2 edit was conceptually right but operationally incomplete: it would parse (`--show`/grep pass) yet not work. Specify a `set:shell`/shebang single-block recipe, distinguish unset vs empty, `rm -f --`, and add behaviour checks. | PLAN.md:Decisions/Risks, TASK-002, TASK-004 |
| — | Round-1 #1 (README two-flow) verified addressed | — | (verified) | Codex confirms the E1-now vs post-E2/E4 split resolves the first-run blocker. | — |
| — | Round-1 #3 (litestream/Docker scope) verified addressed | — | (verified) | Codex confirms the check is now scoped to this phase's surface. | — |
