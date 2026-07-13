# Review Summary — phase-19-5-persistence-integrity

**Rounds:** 3 (post-implementation)
**Fix commits:** 198ea5e, 289b730

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 2        | 1     | 1→reopened | 0      |
| 2     | 1        | 1     | 0        | 0        |
| 3     | 3        | 0     | 1        | 2        |

Round 1's deferred profile-write finding was **reopened** in round 2 (Codex refuted the
deferral with the actual deploy topology) and fixed. Round 3 escalated toward a durable-outbox
architecture; per the round-3 cap + a user scope decision, the remaining residual (redeploy
durability) ships as a documented deploy-infra follow-up and the concurrency findings are
recorded as not-applicable for this single-user deployment.

## Fixes

- `198ea5e` — `training_rollup`/`nutrition_consumed` count `COUNT(computed_at)` (materialized
  rows only) for `n_days`, so a readiness-only placeholder row (from the 19.5 snapshot upsert
  on an unsynced day) no longer inflates the 7/28-day coverage denominator fed to the weekly
  planner. (round-1 #2)
- `289b730` — on profile.yaml write exhaustion the route invalidates the just-committed plan
  row so the next request MISSES and re-generates + re-attempts the write, instead of a
  cache-hit returning 200 with stale constants. Exhaustion→invalidation and exhaustion→recovery
  tests added. (round-1 #1 reopened / round-2 #1)

## Deferred

- (round-3 #1) **Redeploy durability of profile.yaml.** The Dockerfile bakes `profile.yaml`
  into the ephemeral `/app` layer while `app.db` lives on the durable `/data` volume, so a
  routine container replacement can restore an old `profile.yaml` while keeping the committed
  plan → stale constants on subsequent cache hits. The write-*failure* path is now covered
  (invalidation); this loss-of-a-*successful*-write case is a deploy-infra fix — move
  `PROFILE_PATH` onto `/data` with entrypoint seeding, or rely on the existing 6-hourly
  `com.coachapp.profile-backup` snapshot. **User decision: ship now, durable storage as a
  follow-up** (see RUNBOOK "Known limitation: profile.yaml durability"). Also a candidate for
  a small Phase 19.7.

## Rejected

- (round-3 #2) Concurrent request reads the committed plan before profile publication →
  stale-constants 200. **N/A for this single-user self-hosted app** (one user, one client,
  sequential requests); the transactional-pending-state fix is unwarranted here.
- (round-3 #3) Compensating delete-by-`iso_week` could hit a newer row / cleanup failure masks
  the original error. The newer-row race requires a concurrent refresh (**N/A single-user**);
  the cleanup-masks-error robustness point is minor (the original 500 is still surfaced via the
  raise, and the stale row would be re-invalidated on the next attempt).
