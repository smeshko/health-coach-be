# Adversarial Validation — Round 2

**Run:** 2026-06-03 03:05 UTC
**Plan:** e4-p3-seed-reconcile
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

**codex unavailable (quota) — manual review.** Codex was attempted **once** in round 1 with the
`CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` prefix and returned a usage/quota error (resets
~05:18); per the run instruction it was **not** retried in round 2. This round is a **manual verification
pass** confirming the round-1 applies are fully + consistently landed, no new defects were introduced, and
the final-validation task still maps 1:1 to the acceptance criteria.

## Manual verification

**Round-1 applies — verified landed and consistent:**

- **#1 (`activity_summary` has no `origin`)** — applied everywhere it mattered: PLAN Scope (seed inserts
  `activity_summary` via a `date`-PK upsert, no `origin`; reconciliation excludes it), PLAN Decisions (new
  "`origin` lives only on `records` + `workouts`" decision), PLAN Risks (new "non-existent
  `activity_summary.origin` column → `OperationalError`" risk), PLAN Acceptance (the `origin='seed'` +
  three-delta + reconciliation criteria reworded), Research (Architecture Facts + Uncertainty + Constraints +
  Key Files), TASK-002 (upsert path), TASK-003 (scope = `records`+`workouts`; `activity_summary` excluded),
  TASK-004 (reworded checks). A `grep` for `activity_summary` + `origin` co-mentions shows **every** remaining
  one now states "no origin" / "excluded" / "not flagged" — no contradiction survives.
- **#2 (no `ON DELETE CASCADE` → delete children first)** — applied to the seed-idempotency delete (TASK-002:
  child `workout_statistics` deleted before parent seed workouts) and the reconciliation delete (TASK-003:
  same), plus a new PLAN Decision and a new PLAN Risk; Research Constraints/Facts updated.
- **#3 (reconcile `activity_summary` branch moot)** — folded into #1: `activity_summary` removed from the
  reconciliation scope in PLAN + TASK-003 + Research.
- **#4 (final-validation references to `activity_summary.origin`)** — reworded in TASK-004's `origin`,
  three-delta, and reconciliation checks.

**No new defects introduced by the edits:**
- The seed's `activity_summary` upsert (`INSERT … ON CONFLICT(date) DO UPDATE`) is the correct idempotency
  mechanism for a `date`-PK table and is consistent with DB.md §1 "upsert by date" and the E2·P2 schema (no
  surrogate id; `date` PK NOT NULL).
- Reconciliation scoped to `records`/`workouts` still satisfies epic §4/§6 ("leaves 'sync' rows
  authoritative", "keeps … partial-day seed rows"): those are the multi-row, origin-bearing tables where seed
  and sync can coexist; `activity_summary`'s single-row-per-day upsert already collapses the overlap.
- Final-validation maps **1:1** to all 11 PLAN acceptance criteria (verified by listing both side by side);
  each check names a concrete test file + `-k` filter or a grep command — non-circular.
- Whitelist set unchanged and still matches DB.md §1 (activity/recovery + the seven `Dietary*` + `BodyMass`).

**Result:** no applies this round (verification only). Validation stops (a manual round returning only
verified-consistent / no-new-findings is the stop condition, analogous to a codex "approve").

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Round-1 applies #1–#4 verified landed + internally consistent (no `activity_summary.origin` contradiction remains) | — | reject | Verification confirms; nothing to change | — |
| 2 | `activity_summary` date-PK upsert is the correct idempotency mechanism; reconciliation scope still meets epic §4/§6 | — | reject | No defect; consistent with DB.md §1 + E2·P2 | — |
| 3 | Final-validation covers every PLAN acceptance criterion 1:1, non-circular | — | reject | Confirmed by side-by-side listing | — |
