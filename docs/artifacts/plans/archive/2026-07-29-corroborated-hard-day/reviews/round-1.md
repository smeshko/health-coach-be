# Adversarial Review — Round 1

**Run:** 2026-07-29 (UTC)
**Branch:** bug/corroborated-hard-day
**Base:** staging
**Commits reviewed:** 7308c59..c4e39ab
**Reviewer:** Codex (`/codex-local:adversarial-review --wait --scope branch --base staging`)

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the classifier's coverage invariant is unsound, and conflicting valid effort updates produce permanently order-dependent results.

Findings:
- [high] Summed zone minutes are not reliable HR coverage (app/services/daily_metrics_engine.py:491-500)
  Each record's credited seconds are independently added only when its BPM fits z1–z5. Overlapping interval/instant records therefore double-count elapsed time, while valid samples below z1 or above z5 count as zero coverage. For example, two overlapping 13-minute easy intervals can satisfy the 25-minute coverage gate for a 50-minute workout despite only 13 unique minutes; conversely, 50 minutes below z1 appears uncovered. The former can suppress the typed fallback and the latter can activate it, producing an incorrect hard_day and downstream readiness penalty.
  Recommendation: Calculate credited coverage as the union of valid HR-covered time, independently from zone buckets, and cap it at workout duration. Normalize overlapping samples deterministically before accumulating z4/z5 time; add overlap and below-z1 regression tests.
- [medium] Valid effort conflicts permanently depend on payload order (app/services/workout_upsert.py:110-126)
  The repair map keeps the last valid incoming score, but the SQL update refuses to replace any stored value already within 1–10. Consequently, a same-request duplicate pair [uuid/RPE 3, uuid/RPE 9] inserts 3 and cannot apply 9, while reversing the pair stores 9. Sequential valid corrections are likewise ignored forever. Because the new classifier treats a valid low score as disproving evidence, this order-dependent stale state can permanently demote a genuinely hard typed workout and alter readiness and weekly metrics.
  Recommendation: Define authoritative update ordering for valid effort scores. Canonicalize duplicate UUIDs before insertion and persist a monotonic source revision or modification timestamp so newer valid corrections can replace older valid values safely; test both duplicate orderings and sequential valid-to-valid correction.

Next steps:
- Fix coverage accounting and effort update ordering before merge.
- Add the adversarial regression cases described above and run the full service test suite.

## Triage

<!--
Verdict values:
  fix    — real bug; address now in this branch
  defer  — has merit but out of scope; capture as a follow-up
  reject — contradicts an explicit Decision in PLAN.md, or is taste/speculation
-->

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1a | Coverage gate read `sum(zone_minutes)`: overlapping samples double-count toward the 50 % threshold; below-z1 / above-z5 samples count zero coverage | high | fix | Real — the coverage invariant this branch introduced was unsound in both directions (fake coverage suppressing the typed fallback; a full below-z1 recording unable to demote). Coverage is now the union of the chosen source's in-window credit spans, zone-independent and capped at the window length; 5 regression tests added. | daa68aa |
| 1b | Overlap normalization of z4/z5 *accumulation* (promotion signal and `z*_min` day columns) | med | defer | The z-minute crediting semantics are deliberately shared with the day-level `zone_minutes` columns (PLAN.md risk register: drift mitigated by reusing one core, in place since E6). Normalizing overlaps there changes stored `z*_min` values repo-wide — a cross-cutting change to ship deliberately, not as a rider on this branch. Within one source, overlapping HR samples are rare; the coverage gate (the new, load-bearing consumer) is now overlap-proof. | |
| 2a | Valid effort conflicts are order-dependent; newer valid corrections can never replace an older valid stored score | med | reject (behavior) / defer (follow-up) | "A valid stored score is still never overwritten" is an explicit acceptance criterion (Decision 7 amendment), and `test_same_batch_duplicate_leaves_a_valid_first_score_alone` already pins the exact [valid, valid] same-payload case as deliberate. Without ordering metadata (revision / modification timestamp — a schema + sync-contract change), "newer" is indistinguishable from a stale contradicting re-sync, so first-valid-wins is the safe deterministic rule. Supporting true valid→valid correction is filed as a follow-up. | |
| 2b | Backfill docstring over-claims "the LAST valid incoming score wins" — false for a [valid, valid] duplicate pair, where the first (inserted) score wins | low | fix | The docstring contradicted the pinned test one screen below it. Corrected to state the actual contract: last-valid wins the *repair*, but repair only lands on NULL/invalid stored values. | 45f3c3e |
