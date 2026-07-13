# Adversarial Review — Round 2 (post-implementation)

**Run:** 2026-07-13 20:40 UTC
**Branch:** fix/phase-19-5-persistence-integrity
**Base:** staging
**Commits reviewed:** 9a025a7..198ea5e
**Prior rounds in scope:** reviews/round-1.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the #2 fix is sufficient—production metrics writes always stamp computed_at, placeholders do not, and their nutrient fields remain NULL—but the #1 deferral relies on a false failure assumption and still permits silent persistent divergence.

Findings:
- [high] Cache hits permanently suppress profile reconciliation after file-only failure or loss (app/api/routes/weekly.py:179-182)
  The profile write runs only when `cached` is false. After three failures, the plan remains committed; the next ordinary retry is a cache hit and returns without attempting the write. This does not require total disk failure: APP_DB_PATH and PROFILE_PATH are independently configurable, so a read-only or mis-permissioned profile mount can fail while SQLite remains healthy. The repository's container deployment also persists `/data/app.db` while the default `/app/profile.yaml` lives in the replaceable container layer, so a normal container replacement can lose even a successful profile update while retaining the cached plan. Subsequent requests can therefore return 200 while daily briefs and later computations use stale constants.
  Recommendation: Persist the desired Profile or a pending-write marker transactionally with the plan, reconcile it on startup and cache hits, and place profile.yaml on durable storage. If a durable queue remains out of scope, at minimum invalidate the committed plan after write exhaustion and add tests for exhaustion followed by a cache-hit retry and for profile loss across container replacement.

Next steps:
- Reopen round-1 finding #1 based on the repository's actual independent profile/DB paths and container persistence model.
- Keep the COUNT(computed_at) fix; no additional #2 code change is supported by the inspected production write paths.

## Triage

Codex confirms the #2 fix is sufficient and correct. Its #1 push-back is **justified and I was
wrong to defer** — verified: `Dockerfile:42` bakes `profile.yaml` into `/app` (ephemeral) while
`app.db` is on the durable `/data` volume, and `deploy/launchd/com.coachapp.profile-backup.plist`
states litestream backs up app.db but NOT profile.yaml. So a routine redeploy (or an independent
read-only profile mount) diverges them — not a dead-disk event. Reopened as a fix (the minimum
Codex endorses: invalidate the committed plan on write exhaustion). Full durable reconciliation +
placing profile.yaml on durable storage is a deploy-infra follow-up (noted in REVIEW).

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Cache-hit path serves 200 with stale constants after profile-write exhaustion / redeploy loss (round-1 #1 reopened) | high | fix | Deferral rationale refuted by the actual deploy topology; now invalidate the committed plan on write exhaustion → next request MISSES + regenerates. Exhaustion→invalidation + exhaustion→recovery tests added. Deploy-durability (profile.yaml on /data) noted as follow-up | 289b730 |
| 2 | (round-1 #2) COUNT(computed_at) fix — Codex confirms sufficient | — | — | Confirmed correct; no further change | 198ea5e |
