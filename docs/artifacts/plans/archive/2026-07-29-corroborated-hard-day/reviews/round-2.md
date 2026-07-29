# Adversarial Review — Round 2

**Run:** 2026-07-29 (UTC)
**Branch:** bug/corroborated-hard-day
**Base:** staging
**Commits reviewed:** 7308c59..45f3c3e
**Reviewer:** Codex (`/codex-local:adversarial-review --wait --scope branch --base staging` + round-1 focus)
**Prior rounds in scope:** reviews/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the coverage fix repairs the demotion gate, but overlapping hard-zone records still create false promotions, invalid HR can suppress the typed fallback, and valid effort corrections remain permanently ignored.

Findings:
- [medium] Overlapping z4/z5 records still fabricate hard-day promotion (app/services/daily_metrics_engine.py:522-530)
  The round-1 deferral is unsafe because the new classifier directly consumes the unchanged per-record zone sum. Each overlapping record adds its full duration independently. An in-memory reproduction with two identical eight-minute z4 intervals returned 16 hard minutes but only eight unique covered minutes, causing an untyped workout to become a hard day. This can incorrectly apply the readiness penalty and consume weekly hard-day budget. Preserving legacy day-column semantics does not require preserving this defect in the new classifier.
  Recommendation: Calculate classifier z4/z5 minutes from a normalized, non-overlapping timeline with deterministic precedence for conflicting samples. The existing summed semantics can remain isolated to day-level z*_min columns if compatibility requires them.
- [medium] Invalid HR values count as trustworthy coverage and demote typed workouts (app/services/daily_metrics_engine.py:523-530)
  Every non-null HR value contributes a coverage span even when it cannot represent a heartbeat; ingestion places no bounds on HealthRecord.value. A full-window 0-bpm interval produced 50 minutes of coverage and demoted a boxing workout from hard to light. Thus malformed or degraded sensor data can disable the typed fallback, contradicting the stated invariant that bad data should be treated as absent.
  Recommendation: Only count finite, physiologically plausible HR values with an accepted heart-rate unit toward coverage and zone minutes. Treat rejected samples as absent and add zero, negative, non-finite, and wrong-unit regression tests.
- [medium] Valid effort corrections remain permanently stale (app/services/workout_upsert.py:123-131)
  The round-1 rejection does not eliminate the failure: the update predicate only permits replacing NULL or invalid stored values. A legitimate valid-to-valid correction, such as RPE 3 changed to 9 under the same workout UUID, is ignored forever; reversing initial arrival order produces the opposite classification. Because effort is now both promoting and disproving evidence, this pre-existing first-write behavior becomes load-bearing and can permanently misclassify the workout. Calling contradictory input unsafe does not address normal later edits.
  Recommendation: Persist source modification/revision metadata and allow a valid score to replace another valid score only when demonstrably newer. Until ordering exists, do not use an immutable first-seen effort score as authoritative disproving evidence.

Next steps:
- Fix all three classifier invariants and add the described adversarial regressions.
- Run the full service and sync test suites after the changes.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Overlapping z4/z5 records still fabricate promotion — round-1 #1b deferral unsafe | med | fix | Codex's pushback lands: the deferral conflated the shared *credit rules* with the *aggregation*. The classifier's z45 signal is now a union of z4/z5-bucketed spans (cannot exceed wall clock), while the `z*_min` day columns keep their historical per-sample sums — exactly the split Codex proposed. Round-1 #1b is thereby resolved, not just deferred. | 40b9358 |
| 2 | Invalid HR values (0-bpm, negative, non-finite) count as trustworthy coverage and demote typed workouts | med | fix | Real — a regression introduced by the round-1 coverage fix: zone-independent coverage meant *any* non-null value proved recording. Coverage spans are now gated on `_is_plausible_hr` (finite, 25–250 bpm wide sanity bounds, `MIN/MAX_PLAUSIBLE_BODY_WEIGHT_KG` style); implausible samples bucket to no zone AND earn no coverage. Unit checking skipped — HR records carry a single canonical unit through sync, and the value bounds catch the garbage class. | 40b9358 |
| 3 | Valid effort corrections remain permanently stale (pushback on round-1 #2a) | med | defer | The pushback does not change the constraint: without ordering metadata (source revision / modification timestamp — a schema and sync-contract change) a "newer" valid score is indistinguishable from a stale contradicting duplicate, and "a valid stored score is still never overwritten" is a pinned acceptance criterion (Decision 7 amendment) with a test asserting the exact scenario. Codex's own recommendation ("persist revision metadata") is the follow-up being filed; its interim suggestion (don't let first-seen effort disprove) would reopen half the original bug (a mislabelled session with a logged low RPE). Deferred as a real product gap, not rejected. | |
