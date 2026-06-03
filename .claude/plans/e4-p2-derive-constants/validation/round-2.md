# Adversarial Validation — Round 2

**Run:** 2026-06-03 00:26 UTC
**Plan:** e4-p2-derive-constants
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Codex remains quota-exhausted (resets ~05:18); not retried per the caller's note. Manual re-review. -->

```
codex unavailable (quota) — manual review. (Same hard usage limit as round 1; not re-invoked.)
```

**Round-2 manual re-review.** Verifies the four round-1 applies (F2 cadence-type, F4 max_hr estimator,
F7 computed_at compare, F8 "recent" window) are sufficient and consistent across PLAN ↔ RESEARCH ↔ tasks,
and hunts for anything the edits introduced.

### Verification of round-1 applies

- **F2 (cadence type)** — TASK-002 now pins a named `CADENCE_TYPE` constant "to confirm against the real
  corpus"; RESEARCH (Architecture + Uncertainty) and PLAN Decisions all say the same; the fixture inserts
  rows under `CADENCE_TYPE` so the test is agnostic to the exact string. Consistent. Sufficient.
- **F4 (max_hr estimator)** — "bounded max" is now the single pinned behaviour (percentile demoted to an
  optional variant) in TASK-002 + RESEARCH:Uncertainty; the acceptance pins `191` with the `235` spike
  excluded. Estimator ≡ test. Sufficient.
- **F7 (computed_at compare)** — both PLAN:Acceptance and TASK-003:Acceptance now compare against
  `date.fromisoformat(<injected>)` (E3·P1 types it `datetime.date`). Consistent. Sufficient.
- **F8 ("recent" window)** — `RECENT_DAYS (≈90) from the latest sample` is defined identically in TASK-002,
  RESEARCH:Uncertainty, and PLAN:Decisions; the acceptance pins window membership (an older sample excluded).
  Consistent. Sufficient.

### New finding introduced by the F8 edit

- **F11** — defining the trailing-≈90-day window raised the question of whether it also applies to
  `max_hr`. It must **not**: `max_hr` is a near-stationary physiological ceiling "from observed boxing
  peaks" (constitution §3); windowing it to 90 days could miss the true peak (and deflate every zone) if no
  recent max-effort boxing session exists. The rolling anchors (rhr/hrv/cadence) are *current* values and
  correctly windowed. **Applied:** scoped the window to the rolling anchors only and made `derive_max_hr`
  explicitly **corpus-wide** (TASK-002, RESEARCH:Architecture, PLAN:Decisions).

### Other axes (re-checked, no change)

- Zones %max-HR + contiguity-by-shared-edges, the five-section/caps fidelity, TASK dep chain, the
  validate-before-write round-trip guarantee, determinism via `--computed-at`, and the 1:1 final-validation
  coverage of all 9 PLAN acceptance criteria — all still hold; the round-1 edits introduced nothing else.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 10 | Round-1 applies (F2/F4/F7/F8) verified sufficient & consistent across PLAN/RESEARCH/tasks | — | reject | Re-review confirms each landed correctly and is internally consistent; nothing to change. | — |
| 11 | The new trailing-90-day window must not be applied to `max_hr` (physiological ceiling) | med | apply | Windowing max_hr could miss the true boxing peak and deflate all zones; scoped the window to rolling anchors, made `derive_max_hr` corpus-wide. | TASK-002 (window def + derive_max_hr), RESEARCH:Architecture, PLAN.md:Decisions |
