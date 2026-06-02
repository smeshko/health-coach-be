# Adversarial Validation — Round 1

**Run:** 2026-06-03 (UTC)
**Plan:** e2-p1-db-engine-alembic
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship for the plan: it leaves the app.db-only Alembic path and timestamp-preservation contract possible to satisfy with unsafe or non-observable tests.

Findings:
- [high] Alembic imports can bypass the temp DB override (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-004-alembic-init-targeting-app-db-only.md:18-21)
  Verdict: apply. Rationale: TASK-004 tells env.py to import the shared pragma helper from app/database/engine.py, while TASK-001 requires that module to create a module-level engine from get_settings().app_db_path. Because RESEARCH says app_db_path is required, Alembic can fail or bind runtime settings before the test URL override is used. Plan files to change: TASK-001, TASK-004, TASK-005.
  Recommendation: Move pragma setup into a side-effect-free module or make the runtime engine lazy; add an Alembic test that runs with only a temp-file override and no runtime app_db_path dependency.
- [high] Alembic URL ownership is internally contradictory (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-004-alembic-init-targeting-app-db-only.md:13-19)
  Verdict: apply. Rationale: the task says no static sqlalchemy.url so settings always owns the target, but then allows config.get_main_option('sqlalchemy.url') to override settings. A stale alembic.ini or command Config can therefore migrate a stray SQLite file while passing the baseline grep. Plan files to change: PLAN.md, TASK-004, TASK-005.
  Recommendation: Make settings.app_db_path the production source of truth and allow only an explicit test-only override path; add a negative test that static sqlalchemy.url is ignored or rejected.
- [medium] Timestamp tests do not prove verbatim preservation (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-003-europe-sofia-period-key-and-timestamp-helpers.md:16-22)
  Verdict: apply. Rationale: E2 requires ISO-8601 TEXT timestamps preserved verbatim, but parse_ts(value)->datetime plus .utcoffset() checks only preserve offset semantics. Implementations can rewrite '+0200' to '+02:00', alter fractional seconds, or normalize string shape while passing. Plan files to change: PLAN.md, TASK-003, TASK-005.
  Recommendation: Define a validation/storage helper that returns the original accepted timestamp string unchanged, and test raw string equality for the HealthKit offset forms the docs cite plus travel offsets.
- [medium] Engine settings acceptance can pass without testing settings (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-001-sqlalchemy-engine-session-factory-and-wal-pragma.md:29-32)
  Verdict: apply. Rationale: TASK-001 says the module-level engine using settings.app_db_path is proven by constructing make_engine(temp_path), but that only proves the factory accepts an argument. A hard-coded module engine could still pass unless the import-time settings path is isolated and asserted. Plan files to change: PLAN.md, TASK-001, TASK-005.
  Recommendation: Add an import-isolated test that sets/clears the settings cache before importing app.database.engine and asserts engine.url.database equals the overridden app_db_path; keep the factory-path test separate.

Next steps:
- Revise the affected plan/task files before implementation.
- Re-check that TASK-005 maps each PLAN.md acceptance criterion to a non-circular test after the revisions.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Alembic env imports the pragma helper from `engine.py`, whose module-level `engine = make_engine(get_settings().app_db_path)` binds runtime settings at import — can fail or bind the wrong DB before the test override applies | high | apply | Real coherence bug between TASK-001 and TASK-004; the pragma helper must be importable without constructing the runtime engine | TASK-001, TASK-004, TASK-005, PLAN.md:Risks |
| 2 | Allowing `config.get_main_option("sqlalchemy.url")` to override settings means a stale `alembic.ini` could migrate a stray SQLite file while still passing the `baseline` grep | high | apply | Weakens the "app.db only" guarantee; settings must own the prod URL, with a narrow explicit test-only override and a negative test | TASK-004, TASK-005, PLAN.md:Acceptance/Risks |
| 3 | `parse_ts → datetime` + `.utcoffset()` checks prove offset semantics but not **verbatim** string preservation (E2 R2 wants the TEXT preserved as-emitted) | medium | apply | A real observability gap: an impl could rewrite `+0200`→`+02:00` or drop fractional seconds and still pass; need a string-identity storage helper + raw equality test | TASK-003, TASK-005, PLAN.md:Acceptance |
| 4 | Engine-from-settings acceptance only constructs `make_engine(temp_path)`, which proves the factory takes an arg, not that the **import-time** module engine reads `app_db_path` | medium | apply | Closes a non-circular-test gap: add an import-isolated test asserting `engine.url.database` == overridden `app_db_path` | TASK-001, TASK-005, PLAN.md:Acceptance |
