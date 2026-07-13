# Adversarial Review — Round 3 (post-implementation)

**Run:** 2026-07-13 20:58 UTC
**Branch:** fix/phase-19-5-persistence-integrity
**Base:** staging
**Commits reviewed:** 9a025a7..289b730
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship. The compensating transaction is valid when uncontended and deletes no sibling DB effects, but it does not establish plan/profile consistency. Routine container replacement, concurrent cache hits, and cleanup failure still expose stale or incorrectly deleted plans.

Findings:
- [high] Container replacement still causes permanent silent divergence (app/api/routes/weekly.py:181-196)
  Invalidation runs only after an observed write exception. Docker bakes profile.yaml into ephemeral /app while preserving app.db under /data. After a successful profile update, replacing the container restores the baked profile but retains the committed plan. Subsequent requests are cache hits, skip this block entirely, and return 200 indefinitely while computations use stale constants. This is a routine deployment event, so deferring durable profile storage is unjustified.
  Recommendation: Ship durable profile storage now, such as PROFILE_PATH under /data with initialization/migration logic. Prefer also storing the desired profile or its version transactionally and reconciling it on startup and cache hits.
- [high] Committed plan is cache-visible before profile publication succeeds (app/api/routes/weekly.py:170-196)
  get_or_generate_weekly commits before returning, while profile retries and invalidation occur afterward. During that interval, a concurrent request can read the row as a cache hit and return 200 with the new plan while profile.yaml is still stale. The new sequential recovery test cannot exercise this race; deleting the row afterward cannot retract the already-served response.
  Recommendation: Persist a pending/unreconciled publication state in the same transaction as the plan, and make cache hits reconcile or fail until profile publication is acknowledged. Add a two-session concurrency test.
- [medium] Compensating delete is fallible and can target a newer plan (app/api/routes/weekly.py:184-196)
  The second transaction deletes solely by iso_week. If another refresh commits a replacement row while this request retries the file write, the eventual cleanup can delete that newer valid row. Conversely, a concurrent long-lived SQLite writer can make execute or commit fail; the cleanup exception becomes the propagated failure and the original divergent row remains cacheable. The workflow commits no other DB mutation beyond Plans, so uncontended deletion does not lose sibling effects, but this compensation is neither failure-safe nor concurrency-safe.
  Recommendation: Capture the generated plan identity/version and conditionally delete only that row. Handle cleanup failure with rollback and critical logging while preserving the profile-write error; durable pending state remains necessary to prevent subsequent stale cache hits.

Next steps:
- Move profile.yaml onto durable deployment storage before merging.
- Add transactional pending-profile state or an outbox consumed on startup and cache hits.
- Add tests for container profile loss, concurrent cache hits during retries, newer-row replacement, and delete/commit failure.

## Triage

Round-3 cap reached; the stream did not converge but escalated toward a durable-outbox +
reconcile-on-hit + concurrency-safe architecture. Findings #2 and #3 are concurrency races that
cannot occur on this single-user self-hosted app (one user, one client, sequential requests).
Finding #1 (container-replacement durability) is real and routine — but its fix is a deploy-infra
change (move profile.yaml to durable /data), risky to make blind without container-boot testing.
Per protocol (round-3 fix rows on a structural problem), surfaced to the user for the scope call.

| # | Finding | Severity | Verdict | Rationale |
|---|---------|----------|---------|-----------|
| 1 | Redeploy restores baked profile.yaml while keeping the committed plan → permanent stale-constants cache hits | high | (user) | Real, routine; fix = durable profile storage (deploy-infra) or reconcile-on-hit. Surfaced to user |
| 2 | Concurrent request reads committed plan before profile publish → 200 with stale constants | high | reject | Single-user app: no concurrent requests. Documented as N/A for this deployment |
| 3 | Compensating delete-by-iso_week can hit a newer row / cleanup failure masks original error | med | reject/defer | Concurrent-refresh race — N/A single-user; the cleanup-masks-error robustness point noted |
