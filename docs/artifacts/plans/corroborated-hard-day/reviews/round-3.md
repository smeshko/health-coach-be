# Adversarial Review — Round 3

**Run:** 2026-07-29 (UTC)
**Branch:** bug/corroborated-hard-day
**Base:** staging
**Commits reviewed:** 7308c59..40b9358
**Reviewer:** Codex (`/codex-local:adversarial-review --wait --scope branch --base staging` + round-1/round-2 focus)
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship. The duplicate-span union works, but round-2's plausibility fix is incomplete, source selection can discard valid physiology, and valid effort corrections remain permanently stale.

Findings:
- [medium] Wrong-unit HR is still treated as trustworthy physiology (app/services/daily_metrics_engine.py:560-573)
  Crediting checks only the numeric value; it never validates r.unit. The sync schema accepts any unit string and record ingestion persists it verbatim, disproving the triage claim that sync guarantees one canonical unit. A wrong-unit value such as 110 can provide full easy coverage and demote a typed workout, while 172 can fabricate z4 promotion.
  Recommendation: Require the canonical heart-rate unit before contributing coverage or zone minutes, normalize explicitly supported aliases if needed, and add wrong-unit promotion and demotion tests.
- [medium] Invalid or sparse preferred-source data masks complete valid HR data (app/services/daily_metrics_engine.py:545-570)
  The source is selected before plausibility and coverage are evaluated. Consequently, one rank-0 Apple Watch row can exclude a complete lower-ranked Garmin trace and cause a real hard untyped workout to remain light. The prior Apple-only rejection is not enforced by the code: source_rank explicitly supports Garmin and the helper claims dual-device handling.
  Recommendation: Select among sources using plausible, in-window covered duration before rank, with rank only as a tie-breaker; add sparse/invalid-primary versus complete-secondary regressions.
- [medium] Valid effort corrections remain permanently ignored (app/services/workout_upsert.py:123-131)
  The update predicate still permits only NULL or invalid stored scores to change. An ordinary valid 3-to-9 correction for the same workout UUID is therefore ignored forever, leaving the new classifier dependent on arrival order and potentially treating stale low effort as authoritative disproving evidence. Missing revision metadata explains the limitation but is not a safety rationale for shipping it.
  Recommendation: Persist source revision or modification time and accept demonstrably newer valid scores. Until ordering exists, do not let immutable first-seen low effort independently suppress the typed fallback.

Next steps:
- Fix the three classifier invariants and add the stated regressions.
- Rerun the service tests in a writable environment; this review environment could not provide pytest a temporary directory.
- Ruff passed for the changed Python and test files.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Wrong-unit HR (`r.unit` never validated) can earn coverage / zone minutes | med | defer | Codex is right that the schema doesn't *enforce* a unit (round-2 #2's rationale over-claimed — corrected here); but nothing in the existing pipeline checks HR units either: the day-level `zone_minutes` columns have bucketed `r.value` unit-blind since E6, and HealthKit emits heart-rate exclusively as `count/min` in practice. Unit validation is a cross-cutting ingestion concern, same class as the already-deferred `effort_score` bounds at `/sync` (round-1 #7 of validation) — filed together as an ingestion-hardening follow-up, not a rider on the classifier branch. | |
| 2 | Source selected by rank before plausibility/coverage — sparse or invalid preferred-source data can mask a complete lower-ranked trace | med | defer | The single-highest-priority-source rule is an explicit, deliberately reused decision (archived per-day-recompute Decision 4; PLAN.md risk table: "mitigated by reusing the single-source selection rule from `zone_minutes`"). The failure mode is conservative: a masked secondary trace makes zones *absent*, which preserves the typed fallback / legacy behaviour — it never demotes on garbage or fabricates hard minutes. Coverage-aware source selection has merit but changes shared dual-device semantics for the day columns too; follow-up. | |
| 3 | Valid effort corrections remain permanently ignored (third pass on round-1 #2a / round-2 #3) | med | defer | No new information over round 2: the fix Codex itself prescribes (persist source revision / modification time) is a schema + sync-contract change, which is the follow-up being filed. Its interim suggestion (don't let first-seen low effort suppress the typed fallback) would reopen half the original bug — a mislabelled HIIT session with a logged low RPE is exactly the incident this plan fixes. "A valid stored score is still never overwritten" is a pinned acceptance criterion (Decision 7 amendment) with a test asserting the same-payload case. | |

Round 3 produced no `fix` rows — review converged. (Codex's environment could not run pytest; the full suite was run locally after 40b9358: 1419 passed.)
