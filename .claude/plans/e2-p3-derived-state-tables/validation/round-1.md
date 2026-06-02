# Adversarial Validation — Round 1

**Run:** 2026-06-02 23:09 UTC
**Plan:** e2-p3-derived-state-tables
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan can produce a stamped Alembic revision whose contents change later, leaving real databases missing tables while fresh-DB validation still passes.

Findings:
- [high] Partial Alembic revision can be stamped before later tables are added (.claude/plans/e2-p3-derived-state-tables/tasks/TASK-001-daily-metrics-model-and-migration.md:31-34)
  Verdict: reject. Rationale: TASK-001 creates a real `state_tables` revision containing only `daily_metrics`, while TASK-002/TASK-003 later edit that same revision to add four more tables; because Alembic records only the revision id, any DB upgraded after TASK-001 would be considered current and would never run the later table creations. This is a version-skew migration hazard, and the planned fresh temp-DB up/down tests do not exercise an already-stamped partial revision. Plan files to change: `PLAN.md`, `TASK-001`, `TASK-002`, `TASK-003`, and `TASK-004`.
  Recommendation: Either split the work into linear Alembic revisions per task, or move creation of the single `state_tables` revision to the final schema task and explicitly prohibit committing/publishing a partial revision; add final validation that cannot pass with an already-stamped partial migration.

Next steps:
- Revise the task dependency/migration strategy before implementation starts.
- Update final validation to cover the chosen migration strategy, not just fresh-database upgrade/downgrade.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Partial `state_tables` Alembic revision: TASK-001 stamps a revision id holding only `daily_metrics`; TASK-002/003 grow the same revision in-place. If the partial revision were applied to a durable DB, Alembic would treat it as current and never create the later tables — fresh-temp-DB tests wouldn't catch it. | high | apply | Real version-skew hazard worth hardening. (Codex labeled its own finding verdict "reject", but the underlying risk is legitimate — I keep the cohesive single-revision-per-phase design, matching E2·P2, but make the partial-revision rule explicit and add a migration↔metadata **parity** guard that a partial/stale revision cannot pass.) Per-revision-per-task was considered and rejected as overkill for one cohesive phase and inconsistent with E2·P2. | `PLAN.md:Decisions` (revision-completion + parity guard), `PLAN.md:Risks` (partial-revision risk), `PLAN.md:Acceptance` (parity criterion), `TASK-001` (do-not-apply-partial note), `TASK-003` (parity test in RED + REFACTOR + acceptance), `TASK-004` (parity validation command) |
