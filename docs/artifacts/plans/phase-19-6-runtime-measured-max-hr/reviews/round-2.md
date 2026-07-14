# Adversarial Review — Round 2

**Run:** 2026-07-14 05:05 UTC
**Branch:** fix/phase-19-6-runtime-measured-max-hr
**Base:** origin/staging
**Commits reviewed:** d555d89..6ce3c61 (adds fix 6ce3c61 on top of round-1 head)
**Prior rounds in scope:** reviews/round-1.md
**Reviewer:** subagent (Codex still usage-limited until 2026-07-20 — shared-protocol fallback)

## Codex output

<!-- Codex usage-limited; round 2 run by a fresh general-purpose subagent given round-1.md
(verbatim findings + triage) and tasked to verify the fix, challenge the defers/rejects, and
surface regressions. Verbatim below. -->

**(a) Fix is SUFFICIENT — yes.** The three added tests genuinely guard their claims; each was
independently mutation-verified against its exact regression:

| Test | Regression injected | Result |
|---|---|---|
| `..._ceiling_is_inclusive_at_the_boundary` | `<=`→`<` on `_HR_CEILING` | FAILED (caught) |
| `..._as_of_window_width_excludes_next_day` | `+1day`→`+2day` | FAILED (caught) |
| `..._rounds_fractional_peak_not_truncates` | `int(round())`→`int()` | FAILED (caught) |

- 205 boundary, exact `start_date < (as_of+1d)` upper edge (SQLite BINARY collation matches
  Python prefix-ordering → next-day row excluded), and round-vs-truncate (199.6→200) all pinned.
- Parity re-confirmed against `scripts/derive_constants.py:derive_max_hr`.
- No new problem introduced: the `session` fixture is function-scoped over a fresh
  `tmp_path`-migrated `app.db`, so the new tests are isolated — not order-dependent, not flaky,
  no contradiction with siblings. Fix is test-only; production untouched.

**(b) Triage verdicts to overturn: NONE.** Pushed on all five flagged; all hold.
- 1.10 (autoflush) — CONFIRMED correct: records committed by the `/sync` endpoint in a separate
  request; the weekly recompute request inserts no records, so `measured_max_hr` always reads
  committed rows. `autoflush=False` irrelevant.
- 1.8 (alias KeyError), 1.9 (live-path no-op), 1.13 (noop_recompute param) — upheld as rejected.
- 1.7 (in-range artifact ratchet) — defer upheld, with a caveat worth carrying into the
  follow-up: the *runtime* corpus is the continuously-growing live `records` table, so its
  exposure to a single in-range (195–204 bpm) artifact permanently ratcheting the anchor is
  materially larger than the one-shot curated `baseline.db` the offline derivation runs against.
  The "parity with offline" framing understates the risk. Still correctly deferred (accepted
  PLAN D2 decision, violates no acceptance criterion), not overturned.

**(c) New findings: NONE.** The diff is exactly the one-line `new_max_hr=` swap plus the
`measured_max_hr` function; the fix introduced no regression. Branch is clean and ready.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 2.1 | Fix 6ce3c61 sufficient & correct; the 3 guards catch their mutations; no flakiness/order-dependence | — | reject (no action) | Independently mutation-verified; fix is test-only, production untouched. | — |
| 2.2 | No round-1 triage verdict overturned (1.7 defer, 1.8/1.9/1.10/1.13 reject all hold) | — | reject (no action) | Round-2 reviewer pushed on each and confirmed. | — |
| 2.3 | Caveat on the 1.7 follow-up: runtime live-`records` exposure to an in-range artifact > offline `baseline.db` | med | defer | Strengthens the existing 1.7 defer note; carried into REVIEW.md. No code change this phase. | — |

Round 2 produced no new `fix` rows → review complete.
