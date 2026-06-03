# Validation Summary — e5-p2-upsert-services

**Rounds:** 2
**Plan status at validation:** draft
**Run on:** 2026-06-03

> **Codex unavailable (quota) — manual review.** Codex was attempted once with
> `CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` and returned a usage-limit error
> ("You've hit your usage limit … try again at 5:18 AM") with no valid review JSON; per the run
> instructions it was **not** retried. Both rounds are rigorous manual adversarial reviews along the
> same two axes (fidelity to the cited architecture docs; internal coherence).

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 7        | 4       | 0        | 3        |
| 2     | 3        | 0       | 0        | 3        |

## Applied

### Round 1
- `PLAN.md:Scope` + `PLAN.md:Decisions` + `PLAN.md:Acceptance` + `TASK-002` + `TASK-004` + `RESEARCH.md`
  — `WorkoutStat.value` routes to the `maximum` column for `max_*` stats and `average` for `avg_*` stats
  (DB.md §1 has both columns), instead of always `average` (round-1 #1).
- `TASK-003` + `PLAN.md:Decisions` — relocate `now_sofia` to `app/core/time.py` so `/sync` and `/health`
  share one DST-aware `serverTime` helper without a route→route import; `/health` DST tests must stay
  green after the move (round-1 #3).
- `TASK-001` — add an explicit blockquote that records-level "zone-minute capture" = landing HR records
  (E6 derives `daily_metrics` zone-min); the workout `zoneMinutes` writer is TASK-002, not this task,
  so the title can't mislead the implementer (round-1 #4).
- `PLAN.md:Scope` — fix the auth dependency name from `Depends(require_token)` to `Depends(require_auth)`
  (the E1·P2 symbol); the task files were already correct, PLAN.md was the lone drift (round-1 #7).

### Round 2
- None. Round 2 verified the round-1 applies are consistent across PLAN/RESEARCH/tasks and grep-clean,
  found no defect introduced by the edits, and returned **approve** (cap rule → stop at 2 rounds).

## Deferred

- None.

## Rejected

- (round-1 #2) `ActivitySummary.steps` dropped — **correct**: `activity_summary` has no steps column
  (DB.md §1); steps arrive as a `step_count` record → `daily_metrics.steps` (E6). Documented as a
  deliberate, non-lossy drop; not a defect.
- (round-1 #5) `SyncResponse` has no `workoutsDuplicate` while `WorkoutUpsertResult.duplicate` is
  computed — **faithful** to MODELS "SyncResponse" (only `recordsDuplicate` splits); keeping `duplicate`
  on the result aids the idempotency assertion without surfacing a non-spec wire field.
- (round-1 #6) Final-validation coverage — **verified**, not a defect: TASK-004 AC1–AC11 map 1:1 to the
  11 PLAN.md acceptance criteria (AC12 = the lint/test gate), each a concrete named test/command.
- (round-2 #1/#2/#3) Verification-only re-checks (applies consistent; `now_sofia` move made explicit;
  AC coverage intact) — no change required.
