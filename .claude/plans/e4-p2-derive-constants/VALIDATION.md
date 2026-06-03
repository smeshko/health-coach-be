# Validation Summary — e4-p2-derive-constants

**Rounds:** 3 (stopped on approve)
**Plan status at validation:** draft
**Run on:** 2026-06-03

> **codex unavailable (quota) — manual review.** Codex was attempted **once** with the
> `CODEX_DISABLE_IMAGE_GENERATION=1` / `OPENAI_IMAGE_MODEL=""` env fix per the runbook; it returned a hard
> usage/credits limit ("try again at 5:18 AM"), not the `gpt-image-2` image-gen bug — the env fix worked,
> the failure was quota. Per the caller's note (quota EXHAUSTED, do not retry) it was **not** re-invoked.
> All three rounds are rigorous manual adversarial reviews challenging the same two axes: (1) fidelity vs
> the cited architecture docs (DB.md §5/§6, ARCHITECTURE §3/§6, HEALTH-CONSITTUTION §3/§7) + the reused
> E3·P1 `Profile` validator and E4·P1 `baseline.db` shape; (2) internal coherence + final-validation
> coverage. Round 3 returned approve (no applies).

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 9        | 4       | 0        | 5        |
| 2     | 2        | 1       | 0        | 1        |
| 3     | 2        | 0       | 0        | 2        |

## Applied

### Round 1
- TASK-002, RESEARCH (Architecture+Uncertainty), PLAN.md:Decisions — stopped guessing the HK cadence
  identifier; pinned a named `CADENCE_TYPE` constant to confirm against the real corpus (as E4·P1 did),
  derivation/tests agnostic to the exact string (round-1 #2).
- TASK-002, RESEARCH:Uncertainty — made `derive_max_hr` unambiguous: the pinned behaviour is the **bounded
  max** (physiological clamp), with a high percentile only as an optional extra-robust variant, so the
  estimator matches the pinned test (round-1 #4).
- TASK-003:Acceptance, PLAN.md:Acceptance — fixed the "meta stamped" check to compare `meta.computed_at`
  against `date.fromisoformat(<injected>)` since E3·P1 types it as `datetime.date` (a raw-string compare
  would false-fail) (round-1 #7).
- TASK-002 (window def + acceptance), RESEARCH:Uncertainty, PLAN.md:Decisions — defined the undefined
  "recent" as the **trailing ≈90 days from the latest sample** (`RECENT_DAYS`) for the rolling anchors, so a
  7-year corpus yields a *current monthly* anchor and the result is deterministic (round-1 #8).

### Round 2
- TASK-002 (window scope + `derive_max_hr`), RESEARCH:Architecture, PLAN.md:Decisions — scoped the trailing
  window to the rolling anchors only and made `derive_max_hr` explicitly **corpus-wide**: max_hr is a
  near-stationary physiological ceiling "from observed boxing peaks", and windowing it could miss the true
  peak (deflating every zone) if no recent max-effort session exists. (Acceptance wording aligned as part of
  landing this.) (round-2 #11)

### Round 3
- None — re-review confirmed the round-2 apply landed cleanly and consistently; final coherence sweep found
  no new defect (approve).

## Deferred

- None.

## Rejected

- (round-1 #1) Use Karvonen (HR-reserve, uses RHR) for zones instead of %max-HR — the DB.md §5 example is
  pure %max (verified `round(pct·192)` reproduces `[96,125]…[177,192]`; Karvonen would not), and
  constitution §3 names %max-HR as the primary anchor. Already an explicit Decision.
- (round-1 #3) `cadence_current_spm` literal mismatch (§5 example 160 vs constitution prose ~155) — the plan
  **derives** current cadence from the corpus, so neither literal is hard-coded; more faithful than either,
  noted in RESEARCH.
- (round-1 #5) Final-validation may not cover every acceptance criterion — verified TASK-004 maps 1:1 to all
  9 PLAN criteria + lint/test with concrete, non-circular checks. No gap.
- (round-1 #6) TASK dependencies / round-trip guarantee unsound — deps are a clean chain (001→002→003→004);
  validate-before-write + `load_profile` round-trip is exactly epic §4. Sound.
- (round-1 #9) Default `--out` overwrites the E3·P1 example `profile.yaml` — that is the bootstrap's job
  (DB.md §6 writes the file); tests use `tmp_path` so CI never clobbers it. Documented.
- (round-2 #10) Round-1 applies verified sufficient/consistent — confirmatory, nothing to change.
- (round-3 #12, #13) Round-2 apply verified + final coherence sweep — confirmatory; all axes hold, no new
  defect. Approve.
