# Validation Summary — phase-19-4-deterministic-invariant-repair

**Rounds:** 3
**Plan status at validation:** ready
**Run on:** 2026-07-13

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 5        | 3       | 1 (→19.6)| 1 (Meta) |
| 2     | 6        | 6       | 0        | 0        |
| 3     | 2        | 2       | 0        | 0        |

Round 1 invalidated the plan's premise (no safe runtime max-HR anchor source; `compute_zones`
is %max-only) — the plan was rewritten and the scope decided with the user (ship focus, defer
runtime max-HR to a new Phase 19.6, make the zone merge correct-when-reachable). Rounds 2–3
converged on the rewrite (6 applies → 2 medium polish); round 3 called the design coherent and
implementation-ready after the two tightenings, so those were applied and implementation
proceeds (not a rewrite signal).

## Applied

### Round 1
- PLAN.md (full rewrite), TASK-001/002 — focus moved to the DB `plans` row (not `profile.yaml
  Meta`); zone half rescoped to a correct-when-reachable merge; runtime max-HR anchor deferred
  to Phase 19.6 (round-1 #1/#2/#4/#5).

### Round 2
- TASK-001 + Risks — structural `isinstance`/`.get()` guards for legacy `constants: null` /
  null snapshot / non-object JSON (round-2 #1).
- PLAN.md D1/Risks + TASK-001 — out-of-order/backfill scoped as a documented limitation, not a
  guarantee; the "out-of-order-safe" over-claim removed (round-2 #2).
- PLAN.md AC + TASK-002/003 — added an RHR-only-move test (`rhr_baseline == new_rhr`, bounds
  unchanged) and narrowed default byte-identity to `max_hr`/`rhr_baseline` (not cadence)
  (round-2 #3).
- TASK-003 — require two committed adjacent generations transported through
  `metadata["computed"]["constants"]` into `build_deps` + a real `refresh=true` replacement
  (round-2 #4).
- TASK-001 + TASK-003 — prior-week key via `isocalendar()`/`%G-W%V` + W01/W53 boundary tests
  (round-2 #5).
- RESEARCH.md — rewrote the stale "persist in Meta" conclusion to the `inputs_snapshot`
  decision (round-2 #6).

### Round 3
- PLAN.md Scope/D5 + TASK-001 step 0 + TASK-003 — canonicalize `iso_week` at the request
  validator (`%G-W%V`) so cache key / persistence / prior-lookup agree; padded/unpadded tests
  (round-3 #1).
- TASK-001 step 1 + tests + TASK-003 — `.get()`-only guards and the full malformed-input test
  matrix (`{}`, `{"constants": {}}`, invalid value) (round-3 #2).

## Deferred

- (round-1 #4) Runtime measured max-HR anchor derivation — **split into new Phase 19.6**
  (whole-corpus MAX, ratchet-up-only, dual type-alias, tz-safe). Per user decision: safe
  runtime derivation is net-new and zone-corruption-risky; 19.4 makes the merge correct when
  an anchor is provided, 19.6 builds the provider.
- (round-2 #2) Out-of-order/backfill reconciliation of adjacent-equal focus — documented
  limitation; the in-order path (normal usage) alternates. No reconciliation engine.

## Rejected

- (round-1 #5) `Meta.last_quality_focus` in `profile.yaml` — the un-retried post-commit
  `write_profile` makes a profile-file focus a cross-store partial-failure risk. The DB
  `plans` row (committed with the plan) is the transactional home (PLAN D1).
