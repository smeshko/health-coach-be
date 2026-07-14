# Adversarial Validation — Round 3

**Run:** 2026-07-14 04:21 UTC
**Plan:** phase-19-6-runtime-measured-max-hr
**Status at start:** planned
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md
**Reviewer:** independent general-purpose subagent (Codex unavailable for this target — plan
dir gitignored; same fallback as rounds 1–2). Convergence-confirmation pass.

## Codex output

<!-- Verbatim independent-reviewer output below. Do not edit. -->

Convergence confirmed. All six round-2 edits are consistently applied and internally coherent; the round-2 edits introduced no new inconsistency. Grounded against source.

## Result: no apply-level findings — plan is ready

**Check-by-check:**

1. **"tz-safe"/"Sofia-precise" purged (F1/F2).** In the live plan (PLAN/RESEARCH/all tasks) the terms survive only as explicit negations — PLAN.md:35 "NOT Sofia-precise", :120 "NOT Sofia-date precision", RESEARCH.md:26 "rather than a Sofia-precise one". The only literal "tz-safe" hits are in `validation/round-1.md` / `round-2.md`, which are immutable historical records (correct). No remaining contradiction.

2. **Far-future exclusion (F5) consistent + self-consistent.** Appears in both enumeration sites: PLAN.md:49-50 ("inclusion AND far-future exclusion") and TASK-001 Acceptance:37-42 as two assertions (a) in-week peak never dropped, (b) a higher peak "dated well AFTER the `as_of` window (far-future) IS excluded (guards the `start_date < bound` clause)". "well after the window" places it past `as_of + 1 day`, so it is consistent with the conservative-inclusive rule (the +1-day inclusive margin still excludes it).

3. **3-arg signature (F4) uniform.** `measured_max_hr(session, as_of, current_max_hr)` in TASK-001 title (L1), PLAN task-list (L151), Goal, Scope (L22), D2, and Acceptance. No 2-arg `(session, as_of)` form remains anywhere in the live plan.

4. **Parity test placement + no dangling refs.** No live file co-mentions "parity" with "services"; parity is consistently in `tests/scripts/`. TASK-001 Evidence (F6) now carries both a `tests/services … -k measured_max_hr` run and a `tests/scripts/test_derive_constants.py` parity run, with a note that `-k` does not exercise the latter. Consistent.

5. **Grounding sanity.**
   - `datetime.timedelta` on the passed-in `date` → `(as_of + 1 day).isoformat()` yields a `"YYYY-MM-DD"` prefix; lexical `start_date < bound` against ISO-8601 TEXT correctly includes rows dated `as_of` and earlier and excludes `as_of+1`-onward (a same-day timestamped row `"2026-06-23 14:.."` is not `< "2026-06-23"` since the shorter string sorts first). Sufficient; no tz helper needed. Note: `from datetime import date` is already imported at recompute.py:25 but `timedelta` is not — implementer adds it (an ordinary impl step, correctly implied by TASK-001).
   - `RECORD_TYPE_TO_HK["heart_rate"] == "HKQuantityTypeIdentifierHeartRate"` confirmed (healthkit.py:89-90); `Records` exported from `app.database.models` (`__init__.py:14,25`); `func`/`select` are standard sqlalchemy (not yet imported in recompute.py — TASK-001 adds them, no conflict). recompute.py:17 docstring "no DB persistence" is real and TASK-001 REFACTOR (L86-90) correctly schedules its update.

No F1-F6 edit left a dangling reference. The plan is convergent and ready for implementation.

## Triage

No apply/defer/reject findings — convergence confirmed, plan cleared for implementation.

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| — | (none) | — | — | Round-2 edits fully consistent; no new issues introduced | — |
