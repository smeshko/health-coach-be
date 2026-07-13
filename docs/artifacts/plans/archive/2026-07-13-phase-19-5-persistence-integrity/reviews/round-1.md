# Adversarial Review — Round 1 (post-implementation)

**Run:** 2026-07-13 20:20 UTC
**Branch:** fix/phase-19-5-persistence-integrity
**Base:** staging
**Commits reviewed:** 9a025a7..(final validation)
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the weekly retry remains permanently divergent after exhaustion, and snapshot-only daily rows corrupt downstream coverage semantics.

Findings:
- [high] Retry exhaustion leaves an unrecoverable committed-plan/profile split (app/api/routes/weekly.py:168-182)
  `get_or_generate_weekly` commits before the profile write. If all three attempts fail, this route returns 500 but leaves the plan cached. A normal client retry then takes the cache-hit path, `cached` is true, and lines 179-182 skip the profile write entirely; the request can return 200 while `profile.yaml` remains stale. Re-raising surfaces the divergence once but neither prevents nor repairs it, so later planning can use constants inconsistent with the committed plan.
  Recommendation: Persist an idempotent pending-profile-write record or outbox entry in the same transaction as the plan, and drain it after commit and on cache hits/startup until acknowledged. Add a test proving a request after initial exhaustion performs reconciliation instead of silently returning a divergent cached plan.
- [medium] Snapshot-only inserts are not downstream-neutral (app/core/daily_adjuster.py:494-501)
  The insert path creates a `daily_metrics` row with every metric and `computed_at` NULL. Downstream `training_rollup` and `nutrition_consumed` use `COUNT(*)` as `n_days`, so this placeholder is counted as a covered/logged day despite containing no materialized metrics; those counts are serialized into weekly planner inputs. A daily brief requested before sync therefore inflates later 7/28-day coverage and can mislead generated plans. An in-memory execution of this exact insert produced `n_days == 1` for both rollups.
  Recommendation: Either store readiness snapshots separately until a metrics row exists, or redefine downstream coverage to count only genuinely materialized rows, such as rows with non-NULL `computed_at`. Add an integration test covering a snapshot-only row through weekly aggregate serialization.

Next steps:
- Implement durable reconciliation for the post-commit profile write.
- Define and test whether snapshot-only rows count as materialized daily coverage.

## Triage

Both verified. #2 confirmed (`computed_at` exists and is NULL on the snapshot-only insert; the
engine stamps it on every real upsert at `daily_metrics_engine.py:739`; both rollups used
`func.count()`). #1 is real but contradicts an explicit plan Decision (D2 / Out-of-Scope) and
its trigger is a persistent local-disk write failure — for this single-user self-hosted app that
coincides with total disk failure, outside in-process recovery.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Retry exhaustion still permanently diverges (cache-hit path skips the write forever) | high | defer | Contradicts PLAN D2/Out-of-Scope (bounded retry is the epic's stated "retry" option; a durable outbox is deferred). Trigger = persistent disk failure = dead disk on a single-user host; documented known-limitation, follow-up noted | |
| 2 | Snapshot-only `daily_metrics` row inflates `n_days` coverage (COUNT(\*) counts the placeholder) | med | fix | Real bug my change introduced; `n_days` now counts `COUNT(computed_at)` (materialized rows only), placeholder excluded; regression test added | 198ea5e |
