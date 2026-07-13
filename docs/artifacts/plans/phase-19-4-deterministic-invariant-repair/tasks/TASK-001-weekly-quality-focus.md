# TASK-001: Week-keyed quality-focus alternation (DB-persisted, refresh-safe)

## Intent
Consecutive weekly briefs alternate threshold↔VO₂, driven by the prior ISO-week's
persisted pick, independent of the monthly recompute gate, refresh- and legacy-row-safe.

## Steps
0. In `app/api/schemas/weekly.py` `_validate_iso_week`, canonicalize before returning:
   `return f"{int(year_str):04d}-W{int(week_str):02d}"` (round-3 #1/D5). This makes the
   cache key + persistence + lookup agree; add padded/unpadded request tests
   (`2026-W1` → stored/looked-up as `2026-W01`).
1. In `app/core/weekly_planner.py`, add `_prior_week_quality_focus(session, iso_week) ->
   QualityFocus | None`:
   - Prior-week key: `prior_monday = _iso_week_monday(iso_week) - timedelta(days=7)`, then
     format via ISO calendar — `y, w, _ = prior_monday.isocalendar(); key = f"{y:04d}-W{w:02d}"`
     (NOT `%Y`/calendar-year — must be ISO `%G-W%V` semantics so W01 hits the right year,
     round-2 #5). With D5 canonicalization, stored keys are padded, so this matches.
   - `select(Plans.inputs_snapshot).where(Plans.iso_week == key)`; then **structural guards
     using `.get()` everywhere** (round-2 #1 / round-3 #2): return `None` unless
     `inputs_snapshot` is a non-null str that JSON-parses to a dict; `constants =
     parsed.get("constants")` must be a dict; `focus = constants.get("quality_focus")` must
     be a recognised `QualityFocus` value. Any of {null/non-str snapshot, JSONDecodeError,
     non-dict parsed, `constants` missing/null/non-dict (`{}` , `{"constants": null}`),
     `quality_focus` missing (`{"constants": {}}`), unrecognised value} → `None`. Wrap
     `QualityFocus(focus)` in try/except ValueError. **Never index with `[]`.**
2. In `RecomputeConstants.process`, BEFORE the `is_recompute_due` early-return, compute
   `quality = next_quality_focus(_prior_week_quality_focus(session, event.iso_week))`.
3. Emit `quality_focus` in `recomputed` on BOTH branches: not-due →
   `RecomputeConstantsOutput(constants_recomputed=False, profile=profile,
   recomputed={"quality_focus": quality.value})`; due → keep `"quality_focus"` in the bundle.
   Update the output docstring (note `recomputed` is now always non-None carrying at least
   the focus; `constants_recomputed` stays the sole "monthly recompute fired" signal).
4. Delete the dead `_last_quality_focus` helper.
5. Confirm `_quality_run_pick` (`:626`) + `weekly_agent.py` `WeeklyDeps.quality_run_pick`
   need no change (they already read `recomputed`/`constants["quality_focus"]`), and
   `PersistPlanNode` persists it via `inputs_snapshot["constants"]` (now always populated).

## Out-of-order note (round-2 #2)
Alternation is guaranteed only for **in-order** generation. Out-of-order/backfill can leave
adjacent weeks equal (a missing predecessor cold-starts to THRESHOLD). Documented limitation
in PLAN D1; no reconciliation engine.

## Tests (TDD — failing first)
- `test_weekly_planner.py` (session fixture, `_write_profile_yaml`, `_ctx`), committed rows:
  - two adjacent generations: seed a persisted W row with `"threshold"` → generate W+1 →
    emitted `vo2` and the persisted W+1 row carries `"quality_focus": "vo2"`;
    `constantsRecomputed` still False on a not-due week.
  - cold start (no prior row) → `threshold`; and the FULL legacy/malformed matrix, each →
    `threshold` (no crash): `constants: null`, null `inputs_snapshot`, non-object JSON,
    `{}` (missing `constants`), `{"constants": {}}` (missing `quality_focus`),
    `{"constants": {"quality_focus": "garbage"}}` (invalid value) — round-3 #2.
  - canonicalization: an unpadded request `2026-W1` persists as `2026-W01` and the next
    week's prior-lookup matches it (round-3 #1).
  - same-week `refresh`/re-run reads W-1 not W → same focus twice (no double-flip).
  - W01 prior-week resolves to the previous ISO year's W52/W53 (boundary).

## Acceptance
Weekly alternation off the real prior pick (in-order); refresh-idempotent; cold-start &
legacy-row → THRESHOLD (no crash); ISO-year boundary correct; focus persisted in the DB row.
