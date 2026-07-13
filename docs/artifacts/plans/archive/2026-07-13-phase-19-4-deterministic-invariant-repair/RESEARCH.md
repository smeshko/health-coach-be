# Research — Phase 19.4

All citations `file:line` in `app/` unless noted. Grounded via a full-repo read pass.

## Quality-focus flip

- `weekly_planner.py:315` `quality = next_quality_focus(_last_quality_focus(task_context))`;
  `_last_quality_focus` (`:349`) `return None` unconditionally → always `THRESHOLD`
  (`recompute.py:141` `next_quality_focus` — pure involution, cold-start→THRESHOLD).
- The flip is computed **only** inside `RecomputeConstantsNode.process` (`:296`), which is
  monthly-gated by `is_recompute_due` (`:231`, `RECOMPUTE_EVERY_N_WEEKS=4`). On a not-due
  week the node stores `constants_recomputed=False` and no focus (`:299-302`).
- Downstream readers of the focus:
  - `_quality_run_pick` (`:626`) → reads `RecomputeConstants.recomputed["quality_focus"]`
    → `None` on a not-due week (the belt-and-suspenders validator then skips the rule).
  - `weekly_agent.py:178-189` `WeeklyDeps.quality_run_pick` → same `constants` source.
- `plans.inputs_snapshot` carries `constants` (`:758-769`); on a not-due week
  `constants=None` (`:745`). **The 19.4 change makes `recomputed` — hence
  `inputs_snapshot["constants"]` — always carry at least `{"quality_focus": …}`**, so the
  prior week's row is always readable (see "Focus persistence" below). `inputs_snapshot`
  itself and `constants` are nullable on **legacy** rows, so the reader must guard
  structurally (round-2 #1).

## Focus persistence — decided: DB `plans` row, NOT `profile.yaml` `Meta`

**Meta was considered and rejected** (round-1 #5): a profile-file focus + the un-retried
post-commit `write_profile` (`weekly.py:148`) is a cross-store partial failure that can
lose/stale the focus. The transactional home is the `plans` row (`plans.py`,
`inputs_snapshot` JSON TEXT, `UNIQUE(iso_week)`), committed atomically with the plan. No
`Meta` schema change. (`write_profile`'s own atomicity is irrelevant to focus now.)

## Zones — why the branch can't fire at runtime (validation round 1)

- **`compute_zones` is %-of-max-HR ONLY.** `scripts/compute_zones.py:compute_zones(max_hr,
  rhr)` — `rhr` is accepted "conceptually" but the cutpoints are `round(pct * max_hr)`; RHR
  moves **no** bound. So a changed RHR (even the live `rhr_30d_mean`) never re-derives zones.
- **`Profile._zones_consistent_with_max_hr` (`profile.py:258`) enforces `zones.z5.high ==
  thresholds.max_hr`.** A loaded profile's zones are therefore ALWAYS consistent with its own
  anchor — there is no intra-profile drift to detect. The branch can fire **only** on a
  *measured* max-HR that differs from the stored anchor.
- **No runtime measured max-HR source.** `daily_metrics.py` has no `max_hr` column; only the
  offline `scripts/derive_constants.py:141 derive_max_hr()` (whole-corpus bounded `MAX` over
  `records`, sqlite3-based, not imported into `app/`) derives it. A safe runtime version is
  whole-corpus + ratchet-up-only + dual type-alias (`HeartRate` id vs live `heart_rate`
  wire) + tz-safe — net-new, risky (max-HR drives every bound). → **deferred to Phase 19.6.**
- **The current merge (`weekly_planner.py:327-329`) writes only `zones`** → any real anchor
  move would raise the validator (Codex #1). 19.4 fixes the merge to also update
  `thresholds.max_hr`/`rhr_baseline` (correct-when-reachable), demonstrated via an injected
  anchor; the caller stays `new == current` (production no-op) until 19.6.

## Focus persistence — DB, not profile.yaml (validation round 1)

- A profile-file focus + the **un-retried** post-commit `write_profile` (`weekly.py:148`,
  route commits the plan row first) is a cross-store partial failure that can lose/stale the
  focus (Codex #5). The `plans` row (`plans.py`, `inputs_snapshot` JSON, `UNIQUE(iso_week)`)
  is the transactional home: the focus commits atomically with the plan. `PersistPlanNode`
  already writes `inputs_snapshot["constants"]` — making `recomputed` always carry
  `quality_focus` persists it with zero new columns and reads back next week via the prior
  ISO-week row. Refresh of week W reads W-1 (untouched) → deterministic (Codex #3).

## Tests / tooling

- Fixture: real migrated temp-file `app.db` `session` (`tests/{core,services}/conftest.py`),
  WAL + FK-on, `autoflush=False, expire_on_commit=False`.
- `test_weekly_planner.py`: `_write_profile_yaml(..., constants_recomputed_week=…)` +
  `monkeypatch.setenv("PROFILE_PATH", …)` (`:54`); `seed_window` (daily_metrics `:86`),
  `seed_strength_tests` (`:72`), `seed_prior_week_run` (workouts `:110`); `_ctx(session,
  **nodes)` (`:126`). RecomputeConstants branches `:586-682`; a test monkeypatches
  `write_profile` to `pytest.fail` proving no file write (`:633`).
- `test_recompute.py`: pure-fn tests; `next_quality_focus` `:282-303`, `rederive_zones`
  `:432-440`.
- Run: `just test` (`uv run pytest`); lint `just lint` (`ruff check .`, line-length 100,
  py313). No mypy.
