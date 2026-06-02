# Adversarial Validation — Round 1

**Run:** 2026-06-03 (UTC)
**Plan:** e2-p2-ingest-tables
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan leaves key schema guarantees unobservable, so a bad migration can still satisfy final validation.

Findings:
- [medium] Apply: activity_summary date PK can pass validation while allowing NULL keys (.claude/plans/e2-p2-ingest-tables/tasks/TASK-004-final-validation.md:46-48)
  Verdict: apply. Rationale: TASK-004 only proves `date` has TEXT type and `pk=1`; in SQLite, `date TEXT PRIMARY KEY` can still report `pk=1` while allowing multiple NULL rows unless NOT NULL/STRICT/WITHOUT ROWID is used. That breaks the date upsert key and can create duplicate unaddressable activity_summary rows. Inference: SQLAlchemy `primary_key=True` may generate NOT NULL, but the plan's acceptance does not require or test it. Plan files to change: PLAN.md, TASK-003, TASK-004.
  Recommendation: Require `date` to be explicitly non-null in the model/migration, assert `PRAGMA table_info(activity_summary).notnull == 1`, and add a NULL-date insert rejection test.
- [medium] Apply: workout seedability is promised but not covered by final validation (.claude/plans/e2-p2-ingest-tables/PLAN.md:168-174)
  Verdict: apply. Rationale: the plan says workouts use nullable UUIDs for seed rows and TASK-002 requires two NULL UUID workout rows to succeed, but PLAN.md/TASK-004 only map duplicate non-NULL UUID rejection. A migration that makes `workouts.uuid` NOT NULL could pass final validation while breaking the 90-day seed path. Plan files to change: PLAN.md, TASK-002, TASK-004.
  Recommendation: Add a PLAN acceptance criterion and TASK-004 mapping that insert two `workouts` rows with `uuid=NULL` successfully, mirroring the records NULL-tolerance check.

Next steps:
- Patch the plan acceptance and final-validation mapping before implementing the migration.
- Make nullable-key guarantees executable, not just descriptive.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `activity_summary.date` TEXT PK can report `pk=1` while still admitting multiple NULL rows in SQLite (a rowid TEXT PK is not implicitly NOT NULL); the date upsert key could be violated and TASK-004 wouldn't catch it | medium | apply | Real SQLite quirk + observability gap: the upsert/cache key must be NOT NULL; make `date` explicitly non-null and add a `notnull==1` + NULL-date-rejection check | TASK-003, TASK-004, PLAN.md:Scope/Decisions/Acceptance |
| 2 | `workouts` NULL-uuid seedability is asserted in TASK-002 but not mapped in PLAN.md acceptance or TASK-004, so a migration that made `workouts.uuid` NOT NULL would pass final validation while breaking the E4 seed path | medium | apply | Real coherence gap — mirror the `records` NULL-tolerance acceptance onto `workouts`; add the PLAN criterion + TASK-004 mapping | PLAN.md:Acceptance, TASK-002, TASK-004 |
