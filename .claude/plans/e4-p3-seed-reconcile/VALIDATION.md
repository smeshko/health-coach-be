# Validation Summary — e4-p3-seed-reconcile

**Rounds:** 2
**Plan status at validation:** draft
**Run on:** 2026-06-03

> **codex unavailable (quota) — manual review.** Codex was attempted **once** (round 1) with the
> `CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` prefix and returned a usage/quota error
> ("You've hit your usage limit … try again at 5:18 AM") with no valid review JSON. Per the run instruction
> it was **not** retried; both rounds are a rigorous **manual** adversarial review on the same two axes
> (fidelity to the cited architecture docs + internal coherence).

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 5        | 4       | 0        | 1        |
| 2     | 3        | 0       | 0        | 3        |

(Round 1: findings #1–#4 = the four distinct defects applied; #5 = the "confirmed correct" bucket, rejected.
Round 2: verification-only, all three rows confirm no change needed.)

## Applied

### Round 1
- **PLAN.md (Scope/Decisions/Risks/Acceptance/Research) + TASK-002 + TASK-003 + TASK-004 + RESEARCH.md** —
  `activity_summary` has **no `origin`** column (DB.md §1 puts `origin` only on `records` + `workouts`):
  the seed now inserts it via a `date`-PK **upsert** (not an `origin` flag), and reconciliation **excludes**
  it (the date-PK upsert already collapses seed/sync overlap). Removed every wrong `activity_summary.origin`
  assumption. (round-1 #1, #3)
- **TASK-002 + TASK-003 + PLAN.md (Decisions/Risks)** — the `workout_statistics → workouts(id)` FK has **no
  `ON DELETE CASCADE`** and `foreign_keys=ON` (E2·P2/E2·P1), so both the seed-idempotency delete and the
  reconciliation delete now remove **child stats before the parent seed workout** to avoid `IntegrityError`.
  (round-1 #2)
- **TASK-004** — reworded the `origin`, three-delta, and reconciliation final-validation checks to drop the
  `activity_summary.origin` references and assert the `date`-PK / child-first-delete behaviour instead.
  (round-1 #4)

### Round 2
- (none — verification-only round; all round-1 applies confirmed landed and consistent.)

## Deferred

- (none)

## Rejected

- (round-1 #5) Whitelist set, `uuid`/`origin` on `records`/`workouts`, the Europe/Sofia window cut, the
  offline `baseline.db` boundary, and the task-dependency chain — verified **correct** against DB.md
  §0/§1/§6/§7 + ARCHITECTURE §3/§6 + the epic; no change.
- (round-2 #1) Round-1 applies #1–#4 verified landed and internally consistent (a `grep` shows no surviving
  `activity_summary.origin` contradiction) — nothing to change.
- (round-2 #2) The `activity_summary` `date`-PK upsert is the correct idempotency mechanism and the
  `records`+`workouts` reconciliation scope still satisfies epic §4/§6 — no defect.
- (round-2 #3) Final-validation maps 1:1 (non-circular) to every PLAN acceptance criterion — confirmed by a
  side-by-side listing.
