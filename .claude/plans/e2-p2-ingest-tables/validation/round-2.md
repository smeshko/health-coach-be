# Adversarial Validation — Round 2

**Run:** 2026-06-03 (UTC)
**Plan:** e2-p2-ingest-tables
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the round-1 edits are reflected consistently, but final validation still fails the required 1:1 mapping for one PLAN.md acceptance criterion.

Findings:
- [medium] Apply: final validation does not prove workout_statistics columns/types (.claude/plans/e2-p2-ingest-tables/tasks/TASK-004-final-validation.md:42-46)
  Verdict: apply. Rationale: PLAN.md requires the workout_statistics column set, types, and nullability, but TASK-004 maps only FK/index/orphan-FK checks; a migration with missing aggregate columns or nullable workout_id/type could still satisfy this final-validation step. Plan files to change: TASK-004-final-validation.md.
  Recommendation: Add a concrete TASK-004 mapping for workout_statistics columns/types, e.g. a pytest command that asserts id PK, workout_id INTEGER NOT NULL, type TEXT NOT NULL, start_date/end_date TEXT, sum/average/minimum/maximum REAL, and unit TEXT.

Next steps:
- Patch TASK-004 so the workout_statistics PLAN.md acceptance criterion is covered 1:1.
- Keep the round-1 date NOT NULL and workouts NULL-uuid mappings as-is; they are now internally consistent.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-004 maps only FK/index/orphan checks for `workout_statistics`; the PLAN.md acceptance criterion's column set/types/nullability (`id` PK, `workout_id` INTEGER NOT NULL, `type` TEXT NOT NULL, dates TEXT, `sum`/`average`/`minimum`/`maximum` REAL, `unit` TEXT) is not covered 1:1, so a migration with missing/mistyped aggregate columns could pass final validation | medium | apply | Real 1:1 final-validation coverage gap against an existing PLAN.md criterion; add a concrete `PRAGMA table_info(workout_statistics)` mapping in TASK-004 | TASK-004 |

Round-1 edits verified consistent (date NOT NULL + workouts NULL-uuid mappings) — no regressions introduced.
