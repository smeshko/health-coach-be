# Review Summary — corroborated-hard-day

**Rounds:** 3 (Codex, `--scope branch --base staging`)
**Fix commits:** daa68aa..40b9358

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 2 (split into 4 triage rows) | 2 | 1 | 1 |
| 2     | 3 | 2 | 1 | 0 |
| 3     | 3 | 0 | 3 | 0 |

Round 3 produced no fix rows — converged. Full suite green after every fix (1419 passed).

## Fixes

### Round 1
- `daa68aa` — HR coverage for the `hard_day` gate is now a zone-independent **union** of the chosen source's in-window credit spans: overlapping samples no longer double-count toward the 50 % threshold, and below-z1 / above-z5 samples count as real coverage (round-1 #1a). 5 regression tests.
- `45f3c3e` — corrected the effort-backfill docstring, which over-claimed "the LAST valid incoming score wins": for a [valid, valid] duplicate pair the first (inserted) score wins, as the adjacent test pins (round-1 #2b).

### Round 2
- `40b9358` — the classifier's z4+z5 promotion signal is now a union of z4/z5-bucketed spans (duplicated hard samples cannot fabricate minutes the wall clock does not contain, round-2 #1), and coverage spans are plausibility-gated (`25–250` bpm, finite) so a full-window 0-bpm interval no longer demotes a typed workout (round-2 #2). The `z*_min` day columns keep their historical per-sample-sum semantics untouched. 4 regression tests.

## Deferred

- (round-1 #1b → resolved by round-2 #1) Overlap normalization of z4/z5 accumulation — initially deferred as shared-with-day-columns semantics; Codex's round-2 pushback showed the classifier signal could be union-ized without touching the day columns, so it was fixed in `40b9358` rather than staying deferred.
- (round-2 #3 / round-3 #3) **Valid→valid effort corrections are permanently ignored** — a stored valid RPE is never overwritten, so a later legitimate correction (3 → 9 in Apple Fitness) cannot land, and same-payload conflicting valid duplicates resolve first-wins. Supporting true corrections needs source revision / modification-time metadata — a schema + sync-contract change, out of scope here. Until then first-valid-wins is the safe deterministic rule ("a valid stored score is still never overwritten" is a pinned acceptance criterion, Decision 7 amendment).
- (round-3 #1) **HR unit is never validated** — the sync schema doesn't constrain `unit`, and crediting buckets `r.value` unit-blind. Pre-existing pipeline-wide behaviour (the `z*_min` day columns have done the same since E6); HealthKit emits HR exclusively as `count/min` in practice. Belongs to an ingestion-hardening follow-up together with the already-deferred `effort_score` bounds at `/sync`.
- (round-3 #2) **Source selection is rank-first, not coverage-first** — one sparse/implausible sample from the top-ranked source can mask a complete lower-ranked trace. Deliberately reused single-source rule (archived per-day-recompute Decision 4; PLAN.md risk table). Failure mode is conservative: masked data makes zones *absent*, preserving the typed fallback / legacy behaviour — it never demotes on garbage. Coverage-aware selection is a follow-up that would change shared dual-device semantics.

## Rejected

- (round-1 #2a) Allow a newer valid effort score to replace an older valid stored one *in this branch* — contradicts the pinned acceptance criterion and Decision 7's amendment ("a valid stored score is still never overwritten"), and `test_same_batch_duplicate_leaves_a_valid_first_score_alone` pins the exact scenario as deliberate. Without ordering metadata, "newer" is indistinguishable from a stale contradicting re-sync. The underlying product gap is captured in the Deferred list above, not dropped.
