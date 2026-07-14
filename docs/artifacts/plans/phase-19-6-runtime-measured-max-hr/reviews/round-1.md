# Adversarial Review — Round 1

**Run:** 2026-07-14 04:55 UTC
**Branch:** fix/phase-19-6-runtime-measured-max-hr
**Base:** origin/staging
**Commits reviewed:** d555d89..6c1761b
**Reviewer:** subagent ×2 (Codex usage-limited until 2026-07-20 — shared-protocol Codex-unavailable fallback; Risk=high ⇒ two independent parallel lenses)

## Codex output

<!-- Codex was usage-limited ("You've hit your usage limit … try again at Jul 20th"). Per the
shared adversarial-rounds fallback, round 1 was run by two independent general-purpose subagents
given the same adversarial framing + the phase-specific focus (ratchet, dual alias, tz cutoff,
clamp parity, test integrity). Both outputs are pasted verbatim below. -->

### Lens A — implementation-defect focus (verbatim)

**Verdict: No real correctness bugs found.** Findings are all low-severity test-coverage nits.

Critical points — all CONFIRMED correct:
1. Ratchet-up-only: `return max(current_max_hr, int(round(raw)))` with `raw is None → return current_max_hr`. Empty/thin/quiet/above-ceiling all funnel to the None fallback or the `max()` floor. No path lowers the anchor; empty corpus returns `current_max_hr`, never raises. recompute.py:357-359.
2. Dual type-alias: `aliases = {"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}`, matched via `.in_()`, sourced from the single-source map (healthkit.py:90). Both spellings matched, no silent drop. (Offline `derive_max_hr` matches only the HK identifier — the runtime broadening is intentional/correct.)
3. `as_of` lexical cutoff: `start_date < (as_of + 1 day).isoformat()`; verified format-agnostic for both space-separated seed rows and T-separated live rows (they differ only at char ≥10; date diffs land in chars 0-9). Inclusive bias intact — in-week peak can never be dropped; a row dated exactly `as_of+1` correctly excluded. recompute.py:349,355.
4. Physiological clamp parity: `value >= _HR_FLOOR` / `value <= _HR_CEILING` / `int(round(raw))` (80.0/205.0) is parity with offline `derive_max_hr` (derive_constants.py:147-152). tests/scripts parity test guards the constants.
5. `scalar_one_or_none()` on the aggregate: `SELECT MAX(...)` always returns one row (NULL when no match) → returns the scalar or None, never raises MultipleResultsFound.
6. No merge regression: one-line `new_max_hr=` swap; L349-380 merge/validation untouched; 132 tests across the three affected files pass.

Low-severity nits:
- (A-i) Boundary values 80.0 and 205.0 untested — clamp test seeds 70/250, nothing at the floor/ceiling; parity test guards only constant *values*, not the `<=`/`>=` operators. tests/services/test_recompute.py:503-504.
- (A-ii) e2e "shift" test over-claims dual-origin coverage — its comment says the union is "exercised end-to-end," but the 200 peak lives only in the HK-identifier row; the snake_case direction IS covered by `test_measured_max_hr_peak_in_snake_case_origin`, so coverage is adequate, only the comment misleads. tests/core/test_weekly_planner.py.
- (A-iii) No test uses production T-separated `start_date`; all new tests seed space-separated timestamps. Correctness holds (date-prefix comparison is format-agnostic), but the stored format isn't exercised.

### Lens B — design-challenge focus (verbatim)

**Bottom line: no correctness bug.** Code matches the plan's deliberately conservative decisions.

1. `as_of` two-day framing — MATCHES plan, not an off-by-one. `as_of = _iso_week_monday + 7d` (next Monday = week's exclusive end); query `start_date < (as_of + 1d)` admits date-prefix ≤ next Monday = the recompute week + next Monday only = the "~1 day inclusive bias" R3/D2 promise. Does NOT admit two extra days. Nit (low): in the live path `event.iso_week` is the upcoming week, so `as_of` is future and the cutoff excludes nothing — the machinery only matters for deterministic backfill/replay (plan admits "production carries no future HR").
2. In-range sensor artifact permanently ratchets the anchor — MED, real trap but an ACCEPTED plan decision (D2 up-only + ceiling-only guard, parity with offline). A single plausible in-range artifact (195–204, below the 205 gate) permanently raises `max_hr` with no path down, shifting every zone. Acceptance criteria only test a 250 (out-of-range) artifact. Raw MAX vs an Nth-highest/percentile guard is under-justified for a value this load-bearing. Recommend a follow-up.
3. Alias set is half-hardcoded vs the plan's "not hardcoded" claim — LOW. `{"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}` derives only the HK value; the snake_case side is a literal (also the dict key). If that key were renamed this KeyErrors at call time. Minor coupling; key currently exists.
4. Session visibility under `autoflush=False` — LOW/SPECULATIVE, non-issue in prod: records are committed by a prior `/sync` request; recompute does no in-session records insert; tests `session.commit()` first.
5. Upward anchor move breaking merge validation — NON-ISSUE (confirmed safe): validators are `easy_hr_cap < max_hr`, `max_hr > rhr_baseline`, `z5.high == max_hr`; an upward move only widens margins and zones come from `compute_zones(new_max_hr,…)` so `z5.high == max_hr` holds by construction. The try/except is genuine defense-in-depth.
6. Test quality — LOW: (a) the floor case in `clamps_out_of_range_artifacts` is a no-op (70 < every other sample, so dropping `>= _HR_FLOOR` still yields 190 — floor not actually guarded; but a sub-floor value can never be the MAX when in-range rows exist, so it is near-vestigial given up-only MAX); (b) rounding never exercised (all whole numbers → `round` vs truncate indistinguishable); (c) upper-boundary width untested (`excludes_far_future_peak` uses Aug, can't distinguish `< as_of+1d` from `< as_of`/`<=`); dual-alias + parity tests are genuine; `_seed_hr` hardcodes `origin="sync"` even for "SEEDED" rows (harmless — query ignores origin).

No high-severity findings from either lens.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1.1 | Ratchet-up-only: no path lowers the anchor; empty corpus returns current, never raises | high (confirmed correct) | reject | Not a defect — both lenses confirm the invariant holds; matches PLAN D2/D3. Nothing to fix. | — |
| 1.2 | Dual type-alias matches both spellings from RECORD_TYPE_TO_HK | med (confirmed correct) | reject | Not a defect — both spellings matched, no silent drop; matches PLAN R4. | — |
| 1.3 | tz-safe `as_of` lexical cutoff correct & format-agnostic; inclusive bias intact | med (confirmed correct) | reject | Not a defect — verified for T- and space-separated formats; matches PLAN R3/D2. | — |
| 1.4 | Physiological clamp + `int(round)` parity with offline derive_max_hr | med (confirmed correct) | reject | Not a defect — byte-parity with offline; parity test guards constants. | — |
| 1.5 | Merge/validation (weekly_planner L349-380) untouched; upward move can't break validation | med (confirmed correct) | reject | Not a defect — one-line swap; validators only widen on an upward move. | — |
| 1.6 | Under-tested edges: ceiling operator, exact `as_of` upper-bound width, round-vs-truncate (A-i, B6a/b/c) | low | fix | Real coverage gaps in a safety-critical anchor; cheap to close and mutation-verifiable. Added 3 focused guards; each proven to fail on a `<`, `+2d`, and `int()` mutation. | 6ce3c61 |
| 1.7 | In-range sensor artifact permanently ratchets anchor up (no decay/percentile) (B2) | med | defer | Explicit accepted PLAN decision (D2 up-only, ceiling-only clamp; parity with offline). Out of this phase's single criterion. Log as an Epic-19 follow-up: consider an Nth-highest/percentile/sustained-duration guard for the anchor source. | — |
| 1.8 | Alias set half-derived (`"heart_rate"` literal) — KeyError if the wire key is renamed (B3) | low | reject | Circular to "derive" the snake_case key from the very dict it indexes; the literal IS the canonical wire alias (PLAN R4). A rename is a breaking change caught by this line + the seed pipeline. Current code correct. | — |
| 1.9 | `as_of` cutoff is a live-path no-op (future week ⇒ excludes nothing) (B1 nit) | low | reject | Correct observation, not a defect — the cutoff provides deterministic backfill/replay bounding; PLAN R3 already states production carries no future HR. | — |
| 1.10 | Session visibility under `autoflush=False` (B4) | low | reject | Non-issue: records committed by a prior `/sync` request; recompute inserts no records in-session; tests commit before querying. Speculative-only. | — |
| 1.11 | e2e "shift" comment over-claims dual-origin coverage (A-ii) | low | reject | Cosmetic — the snake_case direction is covered by a dedicated unit test (`..._peak_in_snake_case_origin`); only the comment over-claims, coverage is real. | — |
| 1.12 | New tests seed space-separated (not production T-separated) `start_date` (A-iii); `_seed_hr` hardcodes origin (B6 nit) | low | reject | Correctness is format-agnostic (verified — date-prefix only) and origin-agnostic (query ignores `origin`); test data shape doesn't affect the assertions. | — |
| 1.13 | Pre-existing `noop_recompute(dates)` param unused (recompute.py:51, Pyright note) | low | reject | Not in this diff; the param matches the `RecomputeDailyMetrics.__call__(self, dates)` Protocol signature — removing it breaks the seam contract. Ruff clean. Not dead code. | — |
