# Review Summary — phase-19-6-runtime-measured-max-hr

**Rounds:** 2
**Fix commits:** 6ce3c61

> Reviewer note: Codex was usage-limited for the entire window (resets 2026-07-20), so both
> rounds ran via the shared-protocol Codex-unavailable fallback. Round 1 (Risk=high) used **two**
> independent adversarial subagent lenses in parallel; round 2 used a single fresh lens tasked to
> verify the fix and challenge the triage. Every operator-level claim was mutation-verified at
> runtime (guards fail on the injected regression, pass on the real code).

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 13       | 1     | 1        | 11       |
| 2     | 3        | 0     | 1        | 2        |

Both rounds concur: **no correctness bug** in the production change. The runtime
`measured_max_hr` anchor source (ratchet-up-only, dual HR type-alias, physiological clamp,
conservative-inclusive `as_of` cutoff, empty-corpus no-op) is correct and matches the plan's
explicit decisions and offline-derivation parity. The single fix hardens under-tested edges of
that safety-critical query.

## Fixes

### Round 1
- `6ce3c61` — Guard the three under-tested edges of `measured_max_hr` — the `<= _HR_CEILING`
  operator at the 205 boundary, the exact `start_date < (as_of + 1 day)` window width, and
  `int(round())` vs truncation (round-1 #1.6). Both lenses flagged these as coverage gaps in a
  value that anchors every HR zone bound. Each new guard was mutation-verified to fail on a `<`,
  `+2-day`, and `int()` regression respectively; no production code changed.

## Deferred

- (round-1 #1.7 / round-2 #2.3) **In-range sensor artifact permanently ratchets the anchor up.**
  A single plausible in-range artifact (195–204 bpm, below the 205 physiological ceiling) sets
  `max_hr` to that value with no path back down (raw `MAX`, up-only, no decay/percentile/
  sustained-duration guard), shifting every zone. This is an **explicit accepted decision**
  (PLAN D2 up-only + ceiling-only clamp, parity with the offline `derive_max_hr`) and violates no
  acceptance criterion, so it is out of scope for this phase. **Follow-up for Epic 19:** consider
  an Nth-highest / percentile / sustained-duration guard for the runtime anchor source. Round-2
  caveat: the runtime corpus is the continuously-growing live `records` table, so its exposure to
  such an artifact is materially larger than the one-shot curated `baseline.db` the offline
  derivation runs against — the "parity with offline" framing understates the risk.
  *(Not filed in Linear — Linear is not wired for this repo; capture in the Epic 19 tracker.)*

## Rejected

- (round-1 #1.1–1.5) Ratchet-up-only, dual type-alias, tz-safe `as_of` cutoff, clamp+`int(round)`
  parity, and the untouched merge/validation — all **confirmed correct** by both lenses, not
  defects. Matches PLAN D2/D3/R3/R4.
- (round-1 #1.8) Alias set "half-derived" (`"heart_rate"` literal → KeyError if the wire key is
  renamed) — deriving the snake_case key from the very dict it indexes is circular; the literal
  is the canonical wire alias (PLAN R4); a rename is a loud breaking change. Current code correct.
- (round-1 #1.9) `as_of` cutoff is a live-path no-op (upcoming week ⇒ excludes nothing) — a
  correct observation, not a defect; the bound provides deterministic backfill/replay semantics,
  and PLAN R3 already states production carries no future HR.
- (round-1 #1.10) Session visibility under `autoflush=False` — non-issue: records are committed
  by the `/sync` endpoint in a prior request; the weekly-recompute request inserts no records, so
  the query always reads committed rows. Confirmed by tracing the orchestration in round 2.
- (round-1 #1.11) e2e "shift" comment over-claims dual-origin coverage — cosmetic; the snake_case
  direction is covered by the dedicated `..._peak_in_snake_case_origin` unit test.
- (round-1 #1.12) New tests seed space-separated (not production T-separated) `start_date`;
  `_seed_hr` hardcodes `origin="sync"` — correctness is format- and origin-agnostic (verified:
  date-prefix-only comparison; the query ignores `origin`), so test-data shape doesn't affect
  assertions.
- (round-1 #1.13) Pre-existing `noop_recompute(dates)` unused param (Pyright note, recompute.py
  ~L51) — not in this diff; the param matches the `RecomputeDailyMetrics.__call__(self, dates)`
  Protocol signature, so removing it breaks the seam contract. Ruff clean; not dead code.
- (round-2 #2.1, #2.2) Fix sufficiency + no-overturn confirmations — no action.

## Gate

`uv run pytest` → **1349 passed** (was 1346; +3 new guards). `uv run ruff check` → **All checks
passed!**
