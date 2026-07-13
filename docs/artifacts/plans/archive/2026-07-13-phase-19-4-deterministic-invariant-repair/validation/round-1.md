# Adversarial Validation — Round 1

**Run:** 2026-07-13 14:28 UTC
**Plan:** phase-19-4-deterministic-invariant-repair
**Status at start:** ready
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship. The plan cannot satisfy its core invariants on current code: changed max-HR fails profile validation, not-due focus changes are neither transported nor persisted correctly, refreshes double-flip, and the proposed max-HR measurement can ignore live data or lower the anchor after a quiet window. TASK-003 cannot demonstrate the stated acceptance contract.

Findings:
- [high] Zone repair updates zones without updating their anchor thresholds (tasks/TASK-002:14-17)
  TASK-002 preserves the existing merge, which only assigns `dump["zones"]`. A measured max-HR change therefore produces a new Z5 ceiling while retaining the old `thresholds.max_hr`; `Profile.model_validate` rejects this because `zones.z5[1]` must equal `thresholds.max_hr`. An RHR-only change is also incoherent: `compute_zones` ignores RHR, while the task never persists the new `rhr_baseline`, so the same anchor appears changed again on every recompute.
  Recommendation: Apply — require one validated merge of `thresholds.max_hr`, `thresholds.rhr_baseline`, and zones; test max-HR zone movement and RHR persistence separately.
- [high] The not-due quality focus has no durable or shared data path (tasks/TASK-001:10-15)
  Current not-due output has `recomputed=None`; `ComputeBudgetsNode` passes that as `computed.constants`, both validator readers derive from that monthly bundle, and `PersistPlanNode` stages a profile only when `constants_recomputed` is true. TASK-001 says to compute and stamp a not-due focus but does not change the output/feed shape or persistence gate. Consequently the model may not receive the required pick, no profile write is staged, and the next week reloads the same old focus and repeats the same pick.
  Recommendation: Apply — define an always-present typed focus on the existing recompute output, propagate it independently to the USER context, `GeneratePlanNode._quality_run_pick`, and `_quality_run_pick`, and stage every mutated profile.
- [high] A value-only last focus makes refresh and out-of-order generation nondeterministic (PLAN.md:81-86)
  D1 stores only the focus value and D2 flips it on every generated brief. The API accepts an arbitrary ISO week and `refresh=true` deletes and regenerates the same week. A same-week refresh therefore reads that week's persisted focus and flips it again, replacing the plan with the opposite quality session. Historical, future, or concurrent requests likewise mutate the global focus in request order rather than ISO-week order, contradicting the claimed "prior week" semantics.
  Recommendation: Apply — persist a week-qualified focus or derive it from week-keyed Plans, define replay/backfill/gap/concurrency semantics, and test same-week refresh plus out-of-order weeks.
- [high] The proposed trailing max-HR is not the referenced derivation and can ignore live samples (tasks/TASK-002:8-13)
  `derive_max_hr` deliberately uses the whole corpus and explicitly rejects a recent window because it can miss the true peak. The plan instead uses a trailing MAX with a 1-bpm movement gate: a quiet window containing ordinary HR samples is considered sufficient and can sharply lower max-HR, while an in-range sensor artifact can raise it. Runtime rows also use two type representations—seeded HK identifiers and live `heart_rate` wire values—yet the plan does not require both, so a literal mirror of the offline query ignores live sync data.
  Recommendation: Reject [the trailing-window design] — replace with an explicit safe anchor policy, include both stored type aliases and timezone-safe `as_of` bounds, and add sparse-window, artifact, alias, stale, and future-row tests.
- [high] Deferred profile-write recovery can permanently lose the new weekly state (PLAN.md:44-52)
  The plan explicitly defers profile write retry, but the current route commits the Plans row before calling `write_profile`. If that write fails, the weekly plan remains committed while `last_quality_focus` stays stale; a normal retry hits the cached plan and never reapplies the pending profile. The following week can silently repeat the same focus. Atomic replacement prevents a torn file but does not repair this cross-store partial failure, and TASK-003 contains no test or recovery criterion for it.
  Recommendation: Defer — do not ship TASK-001 until profile-write recovery is pulled forward from Phase 19.5 or focus state moves into the DB transaction.

Next steps:
- Revise the plan and task artifacts around atomic anchor merging, week-qualified focus state, and a typed per-week focus feed.
- Expand TASK-003 into a one-to-one acceptance checklist with two persisted weekly runs, refresh/backfill behavior, both anchor paths, insufficient-data fallback, and post-commit write failure.
- Re-run this adversarial review before implementation begins.

## Triage

Verified against current code. `compute_zones` (`scripts/compute_zones.py`) is **%-of-max-HR
only** — `rhr` is accepted but never moves a bound — and `Profile._zones_consistent_with_max_hr`
(`profile.py:258`) enforces `zones.z5.high == thresholds.max_hr`, so a loaded profile's zones
are always consistent with its own anchor. The zone branch can therefore only fire on a
**measured max-HR differing from the stored anchor**, which has no safe runtime source. This
confirms #1 and #4 and forces a scope decision (surfaced to the user).

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Zone merge must update `thresholds.max_hr`/`rhr_baseline` atomically with `zones` or `model_validate` rejects it | high | apply | Confirmed by the `z5.high==max_hr` validator; the current merge is not just dead but would raise on any real move | pending scope decision → TASK-002/PLAN |
| 2 | Not-due-week focus has no transport (`recomputed=None`) and no profile write staged → never persists | high | apply | Confirmed: `PersistPlanNode` stages a profile only when `constants_recomputed` is true; both validators read the monthly bundle | TASK-001/PLAN (redesign) |
| 3 | Value-only global focus double-flips on same-week `refresh=true` and mutates in request- not week-order | high | apply | Confirmed against the weekly route's refresh-regenerate + arbitrary-iso_week contract; focus must be week-keyed | PLAN D1 rewrite/TASK-001 |
| 4 | Trailing-window max-HR is unsafe (can lower the anchor from a quiet window; ignores live `heart_rate` alias) | high | apply | Confirmed: `compute_zones` is %max-only so max-HR is the ONLY zone driver, and it drives ALL bounds — a wrong value corrupts every zone; safe derivation is whole-corpus + ratchet-up + dual-alias = net-new | pending scope decision |
| 5 | Focus in `profile.yaml` + post-commit write failure permanently loses the new focus (cross-store partial failure) | high | apply | Confirmed; resolved for free by moving focus state into the DB transaction (subsumes #3) rather than deferring to 19.5 | PLAN D1 rewrite/TASK-001 |
