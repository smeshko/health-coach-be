# Adversarial Validation — Round 2

**Run:** 2026-06-03 03:05 UTC
**Plan:** e4-p1-build-db-etl
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Codex still unavailable: a third attempt (round-2 prompt) returned the same hard usage-limit error
("try again at 5:18 AM"). The CODEX_DISABLE_IMAGE_GENERATION=1 / OPENAI_IMAGE_MODEL="" env fix was applied;
the failure is quota, not the gpt-image-2 bug. Manual round-2 review per the runbook fallback. -->

**codex unavailable — manual review.** Re-verified the two round-1 applies are sufficient and scanned for
anything the edits introduced or anything previously missed.

### Manual review notes

**Verifying round-1 applies:**
- **round-1 #1 (workouts.id PK vs ARCHITECTURE §3 "no PKs"):** PLAN.md Decisions now explicitly states the
  `workouts.id` AUTOINCREMENT is a build-local parent↔child FK-target join key (not a runtime
  surrogate/`uuid`), that `records`/`activity_summary` carry no PK, and that the raw-dump rule still holds;
  the "Raw column shape" acceptance criterion carries the same reconciliation. Consistent and sufficient.
  No contradiction remains.
- **round-1 #2 (AUTOINCREMENT idempotency):** PLAN.md Decisions + Risks and TASK-002 (acceptance, RED step,
  Notes) now state that `DROP TABLE` clears `sqlite_sequence` (ids restart at 1 → stable across rebuilds)
  and that the idempotency check compares table **contents incl. ids**, not raw file bytes (citing #4's
  reasoning about `ANALYZE`/`sqlite_stat*`/free-page nondeterminism). Consistent across PLAN ↔ TASK-002.

**New scan (incl. issues the edits could introduce):**
- The edits cite "round-1 #4" (the byte-identity reject) as rationale for the contents-not-bytes
  comparison — an appropriate, self-documenting cross-reference, not a defect.
- PLAN idempotency AC ("second run's four-table contents equal the first's") and TASK-002's strengthened
  acceptance ("including ids") remain coherent; "contents" subsumes ids. No mismatch.
- Task dependency chain (T1→T2→T3→T4), final-validation 1:1 coverage, and the no-runtime-leak / streaming /
  fixture-only constraints are unchanged and intact. No new contradictions, orphaned refs, or scope creep
  introduced by the round-1 edits.

**Conclusion:** round-1 applies are sufficient; no new findings. Approve — stop (cap not reached;
round returns no applies).

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | (verification) round-1 #1 fix is sufficient — `workouts.id` reconciliation explicit, no contradiction | — | — | Verified, no action | — |
| 2 | (verification) round-1 #2 fix is sufficient — AUTOINCREMENT/`sqlite_sequence` idempotency explicit across PLAN + TASK-002 | — | — | Verified, no action | — |
| — | No new defects surfaced | — | approve | Plan is internally coherent and faithful to DB.md §0/§1/§6 + ARCHITECTURE §3/§6 | — |
