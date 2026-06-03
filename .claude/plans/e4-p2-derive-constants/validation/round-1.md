# Adversarial Validation — Round 1

**Run:** 2026-06-03 00:25 UTC
**Plan:** e4-p2-derive-constants
**Status at start:** draft

## Codex output

<!-- Codex was attempted once with CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL="" per the runbook;
     it returned a hard usage/quota error, not an image-gen bug. Per the caller's note (quota EXHAUSTED,
     resets ~05:18) it was NOT retried — this round is a rigorous MANUAL adversarial review. -->

```
[codex] Starting Codex task thread.
[codex] Thread ready (019e8adc-7e83-7901-9729-83b60d62ede4).
[codex] Turn started (019e8adc-817a-7003-9599-bbd952e2783b).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (...), visit .../usage to purchase more
        credits or try again at 5:18 AM.
[codex] Turn failed.
# Codex Adversarial Review
Codex did not return valid structured JSON.
- Parse error: You've hit your usage limit. ... try again at 5:18 AM.
```

**codex unavailable (quota) — manual review.** The `CODEX_DISABLE_IMAGE_GENERATION=1` / `OPENAI_IMAGE_MODEL=""`
env fix was applied; the runtime got past the `gpt-image-2` bug — the failure was a hard usage/credits
limit, not image-gen. The manual review below challenges the same two axes: (1) fidelity vs the cited
architecture docs (DB.md §5/§6, ARCHITECTURE §3/§6, HEALTH-CONSITTUTION §3/§7) and the reused E3·P1
`Profile` validator + E4·P1 `baseline.db` shape; (2) internal coherence + final-validation coverage.

### Manual review notes

**Axis 1 — fidelity vs the docs**
- Zones = **%max-HR** is correct: re-verified that `round(pct·192)` for `pct∈{.50,.65,.78,.87,.92,1.00}`
  reproduces the DB.md §5 example `[96,125]…[177,192]` exactly; Karvonen (HR-reserve, uses RHR) would not.
  The plan documents this — no defect. (F1)
- `easy_hr_cap = 180 − age` matches constitution §3 + the DB.md §5 comment (146 at age 34). Correct.
- The five sections / field names / caps (`deficit_pct ≤ 0.20`, `protein_g_per_kg ≤ 2.0`,
  fat low≤high, max_hr>rhr, all five carb multipliers) mirror DB.md §5 and the E3·P1 validator 1:1. Correct.
- **F2** — TASK-002 over-specified the HK cadence identifier (`…RunningStrideLength/cadence`); HealthKit's
  running-cadence type varies by export version and isn't a single obvious quantity type. Over-asserting a
  possibly-wrong `HK…Identifier` is a fidelity risk.
- **F4** — `derive_max_hr` prose said "high percentile / max", but the pinned test asserts a *bounded max*;
  the percentile/max ambiguity could make the estimator under-specified vs the test.
- **F3** — `cadence_current_spm`: DB.md §5 *example* shows 160, constitution §3 prose says "~155". The plan
  **derives** it from the corpus, so neither literal is hard-coded — more faithful than either, not a defect.

**Axis 2 — internal coherence + final-validation coverage**
- TASK deps sane: TASK-001 (pure fn) independent; 002 → 001; 003 → 002; 004 → all. Coherent.
- Final-validation (TASK-004) maps **1:1** to all 9 PLAN.md acceptance criteria (zones-match,
  zones-contiguous, round-trip, meta, easy_hr_cap, data-derived-thresholds, caps, determinism, offline) plus
  lint+test — each with a concrete `pytest -k`/grep/CLI check, none circular. Coverage complete — no defect.
- Round-trip correctness guarantee (construct `Profile(**data)` before write; reload via `load_profile`) is
  sound and is the literal epic §4 check. Determinism via `--computed-at` injection + `sort_keys=False` is
  sound.
- **F7** — the "meta stamped" acceptance compared `computed_at` to the raw injected **string**, but E3·P1
  types it as `datetime.date`; the loaded value is a `date`, so the assertion must compare against
  `date.fromisoformat(...)`. A test as literally written would be a false failure.
- **F10** — `rhr_baseline`/`hrv_baseline_ms`/`cadence_current_spm` were "median of **recent**" with "recent"
  undefined; over a 7-year corpus that's ambiguous (lifetime mean vs current anchor) and weakens determinism
  + the monthly-anchor intent (DB.md §5 ¹/§6).
- **F9** — the default `--out` overwrites the repo-root `profile.yaml` (the E3·P1 example). This is exactly
  the bootstrap's job (DB.md §6) and tests use `tmp_path`, so it's correct/documented — not a defect.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Zones should use Karvonen (HR-reserve) not %max-HR | med | reject | DB.md §5 example is pure %max (verified `round(pct·192)`); constitution §3 "primary anchor = %max"; Karvonen wouldn't reproduce the canonical bounds. Already a documented Decision. | — |
| 2 | Cadence HK `type` over-specified (possibly-wrong identifier) | med | apply | HK running-cadence id varies by export version; pin a named `CADENCE_TYPE` to confirm against the real corpus (as E4·P1 did) rather than guess. | TASK-002, RESEARCH (Architecture+Uncertainty), PLAN.md:Decisions |
| 3 | `cadence_current_spm` 160 (§5 example) vs ~155 (constitution prose) mismatch | low | reject | Plan **derives** current cadence from the corpus, so neither literal is hard-coded — more faithful than either; noted in RESEARCH. | — |
| 4 | `derive_max_hr` "percentile / max" ambiguous vs the pinned bounded-max test | low | apply | Made the pinned behaviour explicit (bounded max; percentile only as an optional extra-robust variant) so estimator ≡ test. | TASK-002, RESEARCH:Uncertainty |
| 5 | Final-validation may not cover every acceptance criterion | high | reject | Verified TASK-004 maps 1:1 to all 9 PLAN criteria + lint/test with concrete non-circular checks. No gap. | — |
| 6 | TASK dependencies / round-trip guarantee unsound | high | reject | Deps are a clean chain (001→002→003→004); validate-before-write + `load_profile` round-trip is exactly epic §4. Sound. | — |
| 7 | "meta stamped" test compares `computed_at` to raw string, but E3·P1 types it `date` | med | apply | Loaded value is a `datetime.date`; the assertion must compare `date.fromisoformat(injected)` or it false-fails. | TASK-003 (acceptance), PLAN.md:Acceptance |
| 8 | "median of **recent**" window undefined → ambiguous + non-deterministic in spirit | med | apply | Defined "recent" = trailing ≈90 days from latest sample (`RECENT_DAYS`), matching the monthly-anchor/seed-window intent; fixture pins window membership. | TASK-002 (window def + acceptance), RESEARCH:Uncertainty, PLAN.md:Decisions |
| 9 | Default `--out` overwrites the E3·P1 example `profile.yaml` | low | reject | That is the bootstrap's job (DB.md §6 writes the file); tests use `tmp_path` so CI never clobbers it. Documented. | — |
