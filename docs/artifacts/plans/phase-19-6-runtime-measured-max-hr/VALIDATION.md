# Validation Summary — phase-19-6-runtime-measured-max-hr

**Rounds:** 3
**Plan status at validation:** planned
**Run on:** 2026-07-14

Reviewer: independent general-purpose subagent all three rounds (Codex could not be used —
the plan dir lives under a **gitignored** `docs/`, so `codex-local:adversarial-review
--scope working-tree` sees no diff; per the shared protocol's Codex-unavailable fallback a
clean subagent ran each round with the same adversarial framing, cross-checked against the
reviewer-of-record's own grounding pass over the same source).

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 4        | 4       | 0        | 0        |
| 2     | 6        | 6       | 0        | 0        |
| 3     | 0        | 0       | 0        | 0        |

Round 3 confirmed convergence with zero findings — **plan cleared for implementation.**

## Applied

### Round 1
- PLAN.md:Scope + PLAN.md:Risks(R3) + PLAN.md:Acceptance + TASK-001(GREEN/Acceptance/Goal) + TASK-002:Acceptance — **tz-safe `as_of` cutoff over-claim (HIGH).** A single SQL `func.max()` with a lexical `start_date <` bound is device-local-date precise only; "widen like `daily_metrics_engine._window`" is unsound because `_window`'s widening is only safe paired with a Python Sofia-date re-filter, which a `func.max()` aggregate can't do. Rewrote to a conservative-inclusive device-local-date bound (`start_date < (as_of + 1 day)` — never drops an in-week peak; may include a near-future row within ~1 day, immaterial for an up-only whole-corpus ceiling) and dropped the Sofia-precision claim throughout. (round-1 #1)
- PLAN.md:Decisions(D4) + TASK-001(Files/RED) — **parity-test fixture scope (MED).** The `derive_constants` fixture and `sys.path.insert(scripts/)` live only in `tests/scripts/conftest.py` (directory-scoped), so the plan's placement of the parity test in `tests/services/` would fail with fixture-not-found / ModuleNotFoundError. Moved the parity assertion to `tests/scripts/`, importing the app-side `_HR_FLOOR`/`_HR_CEILING` from `app.services.recompute`. (round-1 #2)
- TASK-001:REFACTOR — **stale module docstring (LOW).** Added a step to update `app/services/recompute.py`'s "Pure: … no DB persistence" header, since `measured_max_hr` adds a read-only `session`-scoped query. (round-1 #3)
- PLAN.md:Goal + PLAN.md:Scope — **signature/scope doc drift (LOW).** Corrected 2-arg `measured_max_hr(session, as_of)` shorthand to the real 3-arg form, and the "(`session`/`as_of` already in scope)" parenthetical (only `session` is in scope; `as_of` is derived from `event.iso_week`). (round-1 #4)

### Round 2
- PLAN.md:Scope(Tests bullet) — removed the surviving "tz-safe cutoff" test-property wording that contradicted the round-1 rewrite; now "conservative-inclusive `as_of` cutoff (inclusion AND far-future exclusion)". (round-2 #1)
- RESEARCH.md (time.py bullet + start_date-lexical bullet) — reframed the two cutoff mentions away from the debunked widen-then-Python-narrow "tz-safe" convention to the chosen device-local-date conservative-inclusive bound. (round-2 #2)
- TASK-001:Files — removed the now-unused "date helper from `app.core.time`" import instruction; the cutoff needs only `datetime.timedelta` on the passed-in `date`. (round-2 #3)
- PLAN.md:Tasks + TASK-001:title — propagated the 3-arg signature into the two remaining residual spots. (round-2 #4)
- PLAN.md:Scope + TASK-001:Acceptance — tightened the boundary test to assert BOTH inclusion (in-week peak never dropped) AND far-future exclusion (a higher post-window peak is excluded — guards the `start_date < bound` clause). (round-2 #5)
- TASK-001:Evidence — added a `tests/scripts/test_derive_constants.py` evidence run for the D4 parity assertion, which the `-k measured_max_hr` command cannot exercise. (round-2 #6)

## Deferred

- (none)

## Rejected

- (none)

## Load-bearing claims verified against source (no change needed)

- Dual HR type-alias set `{"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}` derived from `app.core.healthkit.RECORD_TYPE_TO_HK` (L89-90), following the `daily_metrics_engine._record_type_aliases` pattern (L110-115) — real and load-bearing.
- Offline `HR_FLOOR=80.0` / `HR_CEILING=205.0` (`scripts/derive_constants.py` L67-68), inclusive `>= floor AND <= ceiling`, `int(round(...))`; the app-side mirror + `tests/scripts/` parity guard is sound. Not cleanly importable from `app/` because `derive_constants.py` L37 does a bare `from compute_zones import` (needs `scripts/` on `sys.path`), so D4's app-side-definition decision holds.
- Ratchet-up-only via `max(current_max_hr, clamped_corpus_max)` and empty-corpus fallback returning `current_max_hr` (no raise, unlike the offline `derive_max_hr`) — correct against `rederive_zones`'s `>= ANCHOR_MIN_DELTA_BPM` (=1) gate (recompute.py L256, L288-291).
- A SQLAlchemy `session` is in scope at the injection point: `session = _session_of(task_context)` at `weekly_planner.py` L299; the `new_max_hr=profile.thresholds.max_hr` no-op is at L335; the merge block L339-370 is untouched; `_iso_week_monday` helper at L226. Existing due-branch tests stay green (empty session → `measured_max_hr` returns current → `rederive_zones` no-op).
- The `as_of` cutoff correctness (the one substantive fix): the conservative-inclusive `start_date < (as_of + 1 day)` bound, with `as_of = _iso_week_monday(event.iso_week) + 7d`, correctly includes an in-week Sunday peak whose device-local prefix rolls to Monday, and excludes far-future rows — verified by lexical-ordering reasoning in round 3.
