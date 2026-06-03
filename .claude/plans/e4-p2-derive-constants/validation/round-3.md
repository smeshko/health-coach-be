# Adversarial Validation — Round 3

**Run:** 2026-06-03 00:27 UTC
**Plan:** e4-p2-derive-constants
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

## Codex output

<!-- Codex remains quota-exhausted (resets ~05:18); not retried per the caller's note. Manual re-review. -->

```
codex unavailable (quota) — manual review. (Same hard usage limit; not re-invoked.)
```

**Round-3 manual re-review.** Verifies the single round-2 apply (F11 — scope the trailing window to the
rolling anchors; `max_hr` corpus-wide) landed cleanly and consistently, and does a final coherence sweep.

### Verification of the round-2 apply (F11)

- `derive_max_hr` is now described as **corpus-wide** in TASK-002, RESEARCH:Architecture, and
  PLAN:Decisions; the trailing-≈90-day window is explicitly scoped to `rhr_baseline`/`hrv_baseline_ms`/
  `cadence_current_spm` only. Consistent across all three files.
- The TASK-002 `derive_max_hr` **acceptance** was aligned to match (a follow-through of landing F11): the
  spike `235` is excluded by the physiological `HR_CEILING` clamp (not a date window), and the test now
  asserts an HR sample older than `RECENT_DAYS` still counts toward `max_hr` — proving max_hr is not
  windowed. No contradiction with the rolling-anchor window acceptance (separate bullet).

### Final coherence sweep (no new findings)

- **Fidelity:** zones=%max-HR (§5 example reproduced), Maffetone easy cap, the five sections + caps
  (deficit≤0.20, protein≤2.0, fat low≤high, max_hr>rhr, five carb multipliers), `baseline.db` raw `records`
  shape (no uuid/origin), Europe/Sofia `computed_at`, and "never opened at runtime" all match the cited
  DB.md §5/§6, ARCHITECTURE §3/§6, constitution §3/§7, and the reused E3·P1 validator + E4·P1 corpus shape.
- **Coherence:** TASK dep chain (001→002→003→004) clean; the validate-before-write `Profile(**data)` +
  `load_profile` round-trip is the literal epic §4 guarantee; determinism via `--computed-at`; contiguity
  by shared integer edges. The final-validation task (TASK-004) still covers **all 9** PLAN acceptance
  criteria 1:1 with concrete, non-circular checks plus lint+test.
- No issue was introduced by the round-1/round-2 edits. **Approve** — no applies this round.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 12 | Round-2 apply (F11) verified — `max_hr` corpus-wide is consistent across PLAN/RESEARCH/TASK-002 incl. its acceptance | — | reject | Re-review confirms F11 landed cleanly; the acceptance wording was aligned as part of landing it; nothing left to change. | — |
| 13 | Final coherence sweep (fidelity + internal + final-validation coverage) | — | reject | All axes hold; no new defect; the edits introduced nothing. Approve. | — |
