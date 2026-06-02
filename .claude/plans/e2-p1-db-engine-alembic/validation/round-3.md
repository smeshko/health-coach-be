# Adversarial Validation — Round 3 (final, cap)

**Run:** 2026-06-03 (UTC)
**Plan:** e2-p1-db-engine-alembic
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the Round 2 WAL fix is still not a guaranteed non-circular validation of the Alembic path.

Findings:
- [high] Alembic WAL check can be made circular by the inspection connection (.claude/plans/e2-p1-db-engine-alembic/tasks/TASK-005-final-validation.md:23-26)
  Verdict: apply. Rationale: TASK-005 says the migrated file must report `wal`, but does not require verification with raw `sqlite3` or a plain engine without `set_sqlite_pragmas`; if the test opens the file through `make_engine`, the inspection connection can switch WAL on and mask an `env.py` that never attached the listener. Impact: Alembic can create a non-WAL `app.db` while final validation passes. Plan files: TASK-004, TASK-005, PLAN.md.
  Recommendation: Specify the migrated-file WAL assertion must open the DB with `sqlite3.connect(db_path)` or a SQLAlchemy engine with no connect listener after `command.upgrade`, then run only `PRAGMA journal_mode`; optionally add a spy/assertion that Alembic registers `set_sqlite_pragmas`.

Next steps:
- Patch TASK-004 and TASK-005 to make the Alembic WAL assertion explicitly non-circular.
- Mirror the same raw/plain-connection wording in PLAN.md acceptance criteria.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | The round-2 WAL-on-migrated-file assertion is circular if the inspection connection goes through `make_engine`/`set_sqlite_pragmas` — that connection itself flips WAL on, masking an `env.py` that never attached the listener | high | apply | Correct and sharp: WAL is a persistent DB-level setting, so the check must open the migrated file with a **raw `sqlite3.connect`** (no listener) to prove the file is *already* WAL from the Alembic run | TASK-004, TASK-005, PLAN.md:Acceptance |

> Cap reached (round 3). The single finding was applied; no further rounds run per the runbook's 3-round cap.
