# Plan: Backend deterministic-invariant repair (Phase 19.4)

Status: in-progress
Branch: fix/phase-19-4-deterministic-invariant-repair
Risk: high
Epic: 19 — Make the numbers trustworthy (audit wave 2, tracked in the iOS repo's docs/artifacts/epics/19-trustworthy-numbers.md)
Phase: 19.4 — Backend deterministic-invariant repair
Created: 2026-07-13

## Goal

Make the threshold↔VO₂ **quality-focus alternation** actually fire. Today
`_last_quality_focus()` hardcodes `None`, so `next_quality_focus()` always returns
`THRESHOLD`, and the flip is only computed on a monthly recompute week. Drive it **every
week** off the **real** prior week's persisted pick so consecutive weekly plans alternate
as designed — with the focus state living in the DB (the `plans` row), committed atomically
with the plan, so a refresh or a post-commit failure can never double-flip or lose it.

Also repair the **zone-rederivation merge** so it is *correct when reachable*: when an
anchor moves, update `thresholds.max_hr`/`thresholds.rhr_baseline` **atomically with**
`zones` (today the merge writes only `zones`, which `Profile.model_validate` would reject).
The runtime *source* of a measured max-HR anchor is explicitly deferred — see Out of Scope.

## Scope

- `app/core/weekly_planner.py`:
  - Compute `quality = next_quality_focus(<prior week's persisted focus>)` on **every**
    weekly brief inside `RecomputeConstants.process`, **before** the monthly `is_recompute_due`
    gate (the node already runs every week; only its internal recompute is monthly-gated).
  - Make `RecomputeConstantsOutput.recomputed` **always** carry `{"quality_focus": …}`
    (not-due week: just that key; due week: the full bundle, which also includes it), so
    both existing focus readers (`_quality_run_pick` at `:626` and the agent's
    `WeeklyDeps.quality_run_pick`, which read `recomputed`/`constants["quality_focus"]`)
    receive a pick every week without further wiring.
  - Add `_prior_week_quality_focus(session, iso_week)` — read the prior ISO week's `plans`
    row's `inputs_snapshot["constants"]["quality_focus"]` (prior-week key via
    `_iso_week_monday`); cold start / gap / unparsable → `None` → `THRESHOLD`.
  - Delete the dead `_last_quality_focus` (hardcoded `None`).
  - Fix the recompute merge: when `zones.changed`, set
    `dump["thresholds"]["max_hr"] = zones.new_max_hr` and
    `dump["thresholds"]["rhr_baseline"] = zones.new_rhr` alongside `dump["zones"]`.
- `app/api/schemas/weekly.py` — canonicalize `iso_week` in `_validate_iso_week`
  (`return f"{int(year):04d}-W{int(week):02d}"`) so an accepted unpadded `2026-W1` becomes
  `2026-W01` everywhere (cache key, persistence, prior-week lookup). Root-cause fix for
  round-3 #1: without it, an unpadded stored row is missed by the padded prior-week lookup
  (cold-starts alternation) and aliases can create duplicate plans for one logical week.
- `app/services/recompute.py` — `ZoneRederivation` already echoes `new_max_hr`/`new_rhr`;
  no kernel change. (`rederive_zones`/`compute_zones`/`next_quality_focus` unchanged.)
- Tests: `tests/services/test_recompute.py` (merge-shape unit) and
  `tests/core/test_weekly_planner.py` (weekly alternation over the `session` fixture;
  refresh idempotence; reachable-and-valid zone merge via an injected differing anchor).

## Out of Scope

- **Runtime measured max-HR derivation → new follow-up Phase 19.6.** `compute_zones` is
  %-of-max-HR only (RHR is accepted but moves no bound), and the profile validator forces
  `zones.z5.high == thresholds.max_hr`, so the zone branch can only fire on a measured
  max-HR that differs from the stored anchor. No such runtime source exists (no per-day
  `max_hr`; only the offline `scripts/derive_constants.py`). A safe derivation is
  whole-corpus + ratchet-up-only + dual type-alias + tz-safe — net-new work with real
  zone-corruption risk (max-HR drives every bound). 19.4 makes the merge correct *when an
  anchor is provided*; 19.6 builds the provider. (User decision, validation round 1.)
- `Meta.last_quality_focus` in `profile.yaml` — **rejected**: a profile-file focus + the
  post-commit `write_profile` (a known un-retried failure point, Codex #5) is a cross-store
  partial-failure that can lose or stale the focus. The DB `plans` row is the transactional
  home. No `Meta` schema change.
- Backend persistence integrity (readiness upsert, profile.yaml write retry, workouts
  index) — Phase 19.5.

## Research Summary

See [RESEARCH.md](RESEARCH.md). Load-bearing, all re-verified against current code:

- Node order `LoadAggregatesNode → RecomputeConstants → ComputeBudgetsNode →
  GeneratePlanNode → ValidatePlanNode → PersistPlanNode` (`weekly_planner.py:6`).
  `RecomputeConstants` runs **every** week; only the cadence/zones/strength recompute is
  monthly-gated (`is_recompute_due`, `:299`).
- The focus is read from `recomputed`/`metadata["computed"]["constants"]["quality_focus"]`
  by both the validator (`:626`) and the agent (`weekly_agent.py:174`). On a not-due week
  `recomputed=None` → no pick reaches either (Codex #2). Making `recomputed` always carry
  `quality_focus` fixes both readers at one seam.
- `PersistPlanNode` writes `inputs_snapshot = {"aggregates":…, "constants": recomputed}`
  keyed by `iso_week` (UNIQUE) (`:758-769`). With `recomputed` always populated, the focus
  persists on every plan row → readable next week. `refresh=true` regenerates week W but
  reads week **W-1**'s row → deterministic, no double-flip (Codex #3).
- `Profile._zones_consistent_with_max_hr` (`profile.py:258`) enforces
  `zones.z5.high == thresholds.max_hr`; the current merge writes only `zones` (`:327-329`)
  → any real anchor move would raise (Codex #1). `ZoneRederivation` already carries
  `new_max_hr`/`new_rhr` (`recompute.py:264`) for the merge to use.

## Decisions

- **D1 — Per-week focus is derived from the prior ISO-week's persisted `plans` row and
  stored back on this week's row** (in the existing `inputs_snapshot["constants"]`). Not a
  profile field. Week-keyed and DB-transactional (committed with the plan — no cross-store
  loss). The prior-week key is ISO-correct (`date.isocalendar()` / `%G-W%V`, not
  calendar-year formatting, so W01 queries the right ISO year — round-2 #5). The reader
  guards structurally against legacy `constants: null` / null `inputs_snapshot` / non-object
  JSON / missing key / invalid value → `None` → THRESHOLD (round-2 #1).
  - **Scope of "alternates": in-order generation (the normal weekly path).** A refresh of
    week W reads W-1 (untouched) → same focus, no double-flip. **Out-of-order/backfill is a
    documented limitation, not a guarantee:** generating W+1 before W commits makes W+1
    cold-start to THRESHOLD, and a later W can also land THRESHOLD (adjacent-equal). This is
    deterministic and self-consistent but not alternating across a backfilled gap; a
    reconciliation engine is out of scope (round-2 #2).
- **D2 — Drive the flip every week, independent of the monthly recompute gate**, by
  computing it before the gate in `RecomputeConstants` and always emitting `quality_focus`
  in `recomputed`. `constants_recomputed` (the bool) still means only "the monthly recompute
  fired".
- **D3 — Zone merge is correct-when-reachable: atomically update `thresholds.max_hr`,
  `thresholds.rhr_baseline`, and `zones`** so an injected/hand-edited/future-19.6 anchor
  move produces a *valid* Profile. The caller still passes `new == current` (documented
  production no-op) until 19.6 supplies a real anchor.
- **D4 — Reuse kernels verbatim** (`next_quality_focus`, `compute_zones` via
  `rederive_zones`); only inputs/plumbing change, so validators hold by construction.
- **D5 — Canonicalize `iso_week` at the request boundary** (`%G-W%V`, zero-padded), so the
  cache key, persistence, and prior-week lookup all agree on one key per logical week
  (round-3 #1). Idempotent for already-canonical keys (the norm); legacy noncanonical rows
  self-heal (cold-start once, then canonical thereafter).

## Risks

- **`recomputed` overloaded to always carry `quality_focus`.** Mitigated: `constants_recomputed`
  stays the sole "monthly recompute fired" signal; the `constantsRecomputed` payload flag
  reads that bool, not `recomputed`'s presence — verified at `:756`. A test pins that a
  not-due week still reports `constantsRecomputed=false` while emitting a focus.
- **Prior-week read on a gap/cold start/legacy row.** `_prior_week_quality_focus` returns
  `None` (→ THRESHOLD) on a missing row, a **legacy `constants: null`** row, a null
  `inputs_snapshot`, non-object JSON, a missing/invalid `quality_focus` — via structural
  `isinstance` guards (round-2 #1), pinned by cold-start + legacy-row tests. The prior-week
  key uses `isocalendar()`/`%G-W%V` so W01 resolves to the right ISO year (round-2 #5).
- **Out-of-order/backfill (round-2 #2).** Adjacent stored weeks can be equal when a
  predecessor is generated late — deterministic but not alternating across a gap. Accepted
  as a documented limitation (D1); the in-order path (normal usage) alternates.
- **Refresh double-flip (Codex #3).** Resolved by reading W-1, not W — pinned by a
  same-week-refresh idempotence test.
- **Reachable-but-unsourced zone branch.** The merge is demonstrated valid via an injected
  anchor in tests; production stays a no-op until 19.6. TASK-003 asserts the injected-anchor
  merge validates *and* the default path leaves zones byte-identical.

## Acceptance Criteria

- [ ] Consecutive weekly briefs alternate quality focus, demonstrated by **two committed
  adjacent generations** (persisted W `threshold` → generate W+1 → persisted W+1 `vo2` →
  generate W+2 → `threshold`), with the focus transported through
  `metadata["computed"]["constants"]` into `GeneratePlanNode.build_deps` (not fed directly
  to the helpers — round-2 #4). A cold start (no prior row, incl. legacy `constants: null`)
  opens on `threshold`. Green on a **not-due** week (independent of the monthly gate), which
  still reports `constantsRecomputed=false`. W01/W53 ISO-year boundary covered.
  Failing-then-passing shown.
- [ ] Both focus readers (`_quality_run_pick` and the agent `WeeklyDeps`) receive the same
  per-week pick on a not-due week (no divergence).
- [ ] A **same-week `refresh=true`** re-emits the **same** focus (reads W-1, not W) — no
  double-flip. Pinned by a test.
- [ ] Zone merge is correct-when-reachable, **both anchor paths**:
  - injected **max-HR** move → `Profile` validates, `zones == compute_zones(new_max_hr,
    new_rhr)`, `thresholds.max_hr == new_max_hr`, `thresholds.rhr_baseline == new_rhr`;
  - injected **RHR-only** move (`new_rhr != current`, `new_max_hr == current`) → `zones`
    bounds **unchanged** (compute_zones ignores RHR) but `thresholds.rhr_baseline ==
    new_rhr` (proves the stale-RHR omission is closed, round-2 #3);
  - default path (`new == current`) → `zones`, `thresholds.max_hr`, `thresholds.rhr_baseline`
    byte-identical (assert those fields specifically, since `cadence_current_spm` may change
    independently on a due run — round-2 #3).
  Failing-then-passing shown.
- [ ] `just test` green; `just lint` (`ruff check .`) clean.

## Tasks

- [ ] TASK-001: Week-keyed quality-focus alternation (DB-persisted, refresh-safe)
- [ ] TASK-002: Correct-when-reachable zone-rederivation merge
- [ ] TASK-003: Final validation
