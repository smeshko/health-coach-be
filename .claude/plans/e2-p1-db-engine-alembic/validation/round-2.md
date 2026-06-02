# Adversarial Validation — Round 2

**Run:** 2026-06-03 (UTC)
**Plan:** e2-p1-db-engine-alembic
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship for the plan: round-1 fixes mostly landed, but the final mapping still lets Alembic miss the WAL invariant, and the lazy-engine fix left stale engine-export instructions that can reintroduce the import-time binding bug.

Findings:
- [high] Alembic-created DB can skip WAL while final validation still passes (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-005-final-validation.md:20-21)
  Verdict: apply. Rationale: TASK-005 maps WAL validation only to make_engine(), not the Alembic upgrade path; an env.py that fails to attach set_sqlite_pragmas can still pass final validation while alembic upgrade head creates a non-WAL app.db, violating E2 R1/acceptance and hiding a Litestream backup gap. Plan files to change: PLAN.md, TASK-004, TASK-005.
  Recommendation: Add a TASK-004/TASK-005 Alembic integration assertion that after command.upgrade(cfg, 'head') on the temp file DB, querying that migrated file returns PRAGMA journal_mode == 'wal'; map PLAN.md WAL acceptance to this migration-path check as well as the runtime-engine check.
- [medium] Stale engine export contradicts the lazy get_engine fix (.claude/plans/e2-p1-db-engine-alembic/PLAN.md:38)
  Verdict: apply. Rationale: PLAN.md still requires app.database.__init__ to re-export engine even though TASK-001 removed module-level engine construction; following the stale scope can recreate the round-1 import-time settings bind, while TASK-005's public API check would not catch the contradiction because it imports get_engine only. Plan files to change: PLAN.md, RESEARCH.md.
  Recommendation: Remove engine from the PLAN.md and RESEARCH.md re-export/API examples, replace any useful-command references with get_engine(), and keep the public API contract consistently centered on make_engine/get_engine/set_sqlite_pragmas.
- [medium] Naive datetime inputs can produce machine-dependent period keys (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-003-europe-sofia-period-key-and-timestamp-helpers.md:24-27)
  Verdict: apply. Rationale: TASK-003 says to_sofia requires aware datetimes but prescribes dt.astimezone(SOFIA) and only tests naive strings; in Python, astimezone() on a naive datetime uses the host local timezone, so direct period_date()/iso_week() calls can silently derive different cache keys across dev, CI, and containers. Plan files to change: PLAN.md, TASK-003, TASK-005.
  Recommendation: Specify an explicit aware-datetime guard used by to_sofia(), period_date(), and iso_week(); add tests that direct naive datetime inputs raise, and map that check in TASK-005.

Next steps:
- Patch the plan/task docs before implementation.
- Re-run this review after the WAL migration-path assertion and lazy-engine API cleanup are reflected in TASK-005.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | WAL acceptance maps only to `make_engine()`, not the Alembic upgrade path — `env.py` could miss `set_sqlite_pragmas` and `alembic upgrade head` would create a non-WAL `app.db` while validation still passes | high | apply | Real gap vs epic R1/§4: WAL must hold on the **migrated** file too; add a post-`upgrade head` `PRAGMA journal_mode=='wal'` assertion and map it | TASK-004, TASK-005, PLAN.md:Acceptance/Risks |
| 2 | Stale `engine` re-export in PLAN.md/RESEARCH.md contradicts the lazy `get_engine()` fix and could reintroduce the import-time bind | medium | apply | Internal inconsistency introduced by the round-1 edit; the API contract must consistently use `get_engine()` (no module-level `engine`) | PLAN.md:Scope, RESEARCH.md |
| 3 | `to_sofia`/`period_date`/`iso_week` use `dt.astimezone(SOFIA)`; on a **naive** datetime that silently uses the host local tz → machine-dependent period keys; only naive *strings* were tested | medium | apply | Real correctness/reproducibility bug for the cache keys; add an explicit aware-datetime guard + a test that naive **datetime** inputs raise | TASK-003, TASK-005, PLAN.md:Decisions/Acceptance |
