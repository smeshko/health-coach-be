# Adversarial Validation — Round 1

**Run:** 2026-07-14 04:21 UTC
**Plan:** phase-19-6-runtime-measured-max-hr
**Status at start:** planned
**Reviewer:** independent general-purpose subagent (Codex could not be used — the plan
dir lives under a **gitignored** `docs/`, so `codex-local:adversarial-review --scope
working-tree` sees no diff; per the shared protocol's Codex-unavailable fallback a clean
subagent ran the round with the same adversarial framing + explicit file paths). Findings
were cross-checked against the reviewer-of-record's own grounding pass over the same source.

## Codex output

<!-- Verbatim independent-reviewer output below. Do not edit. -->

I have enough to report. All plan claims grounded against source.

## Findings — validate-plan: phase-19-6-runtime-measured-max-hr

**1. tz-safe `as_of` cutoff cannot be Sofia-date-precise with a single SQL `func.max()` and no Python re-filter — HIGH**
The plan tells the implementer to compute the peak with one `select(func.max(Records.value)).where(start_date < <upper bound widened like _window>)` and calls that "Sofia-day aware / tz-safe" (TASK-001 GREEN; PLAN Scope; R3). But `daily_metrics_engine._window` (L159-166) is only Sofia-precise because it is *paired* with a Python narrowing (`_instant_records` L263-269: `to_sofia(parse_ts(r.start_date)).date() == day`). `records.start_date` is device-local wall-clock TEXT, so a row's text-prefix date and its Sofia date can differ by ±1 day in *either* direction depending on offset. Concretely, two rows both text-prefixed `2026-06-22` can have Sofia dates Sunday (in-week, must include) and Monday (future, must exclude) — no single lexical `<` bound separates them. A `func.max()` aggregate can't re-filter in Python, so the cutoff is device-local-date ±1 day, not Sofia-precise. R3's promised mitigation ("a sample straddling the `as_of` boundary at a non-UTC offset") therefore can't pass as a Sofia-precise assertion; the implementer will either redesign mid-task (fetch near-boundary candidates + max in Python) or silently weaken the test.
Failure scenario: boundary unit test seeds a Sunday-in-week HR peak from a device at `+13:00` (text prefix = next Monday) → excluded by the lexical bound → anchor misses the true peak; or a `-11:00` Monday/future row leaks into the MAX.
Verdict: **apply** — Given this is a whole-corpus MAX and production never has future HR data, the honest fix is to drop the Sofia-precision claim: use a conservative widened upper bound (`as_of + 1 day`) so no in-week row is ever missed, state that near-future rows within 1 day may be included (immaterial in production), and rewrite R3's boundary test to assert that conservative behavior rather than Sofia-precision. (Alternative: add an explicit Python-narrowing step and budget it.) Files: TASK-001, PLAN.md (Scope "tz-safe" bullet + R3).

**2. D4 parity test as specified will not run in `tests/services/` — MED**
PLAN D4 / TASK-001 RED say to add the `HR_FLOOR`/`HR_CEILING` parity test to `tests/services/test_recompute.py` "using the same module-loading fixture `tests/scripts/test_derive_constants.py` uses." That `derive_constants` fixture **and** the `sys.path.insert(0, scripts/)` that makes `import derive_constants` resolvable both live only in `tests/scripts/conftest.py` (verified: no `tests/conftest.py`, no `pythonpath` in pyproject, no `scripts/__init__.py`). pytest fixtures are directory-scoped, so they're invisible to `tests/services/`. Worse, TASK-001's own Evidence command `pytest tests/services/test_recompute.py -k measured_max_hr` runs that dir in isolation, so `tests/scripts/conftest.py` isn't even collected and `scripts/` isn't on the path. A direct `from scripts.derive_constants import HR_FLOOR` also fails because derive_constants L37's bare `from compute_zones import compute_zones` needs `scripts/` on `sys.path` (exactly the reason D4 gives for not importing it).
Failure scenario: parity test raises `fixture 'derive_constants' not found` / `ModuleNotFoundError`.
Verdict: **apply** — Pick one: (a) place the parity test in `tests/scripts/` (it needs no `session`, only the constants), (b) replicate the `sys.path.insert` + `importlib` load inside the `tests/services` test, or (c) hoist the fixture/path-insert into a new `tests/conftest.py`. Files: PLAN.md (D4), TASK-001.

**3. `recompute.py` module docstring "Pure: … no DB persistence" goes stale — LOW**
The module currently imports no sqlalchemy/models and is all pure helpers; its docstring opens "Pure: no FastAPI/HTTP imports, no DB persistence, no LLM." Adding `measured_max_hr(session, …)` introduces `from sqlalchemy import func, select`, `from app.database.models import Records`, and live `session.execute(...)` reads. D1 justifies the module home well, but no task updates the docstring, so it will mislead the next reader (a Session-querying function in a file that advertises purity).
Verdict: **apply** (cheap) — add a docstring-update step to TASK-001 noting the new DB-read query fn. File: TASK-001.

**4. Signature shorthand / "in scope" wording drift — LOW**
PLAN title, Goal, and Scope (L22) call it `measured_max_hr(session, as_of)` while the real signature (D2/Acceptance/tasks) is 3-arg `(session, as_of, current_max_hr)`; PLAN L40 says "(`session`/`as_of` already in scope)" but only `session` is in scope — `as_of` must be computed from `event.iso_week` (TASK-002 does this correctly; `timedelta`/`func`/`select` are already imported in `weekly_planner.py`, verified).
Verdict: **defer/apply-if-touching** — harmless doc inconsistency; tidy the 2-arg mentions and the "in scope" parenthetical. File: PLAN.md.

## Claims that check out (no action)
- Injection point `weekly_planner.py` L329-337, `_session_of` L114-125, merge L339-368, `_iso_week_monday` L226-229 — all accurate.
- Constants parity: offline `HR_FLOOR=80.0`/`HR_CEILING=205.0` (derive_constants L67-68), inclusive `>= floor AND <= ceiling`, `int(round(...))` — the SQL port mirrors it exactly. Dual alias `{"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}` is real and load-bearing (healthkit L89-90; daily_metrics `_record_type_aliases` L110-115).
- Existing weekly-planner tests stay green under TASK-002: the due-branch spy test (L623) and merge-revalidate test (L662) seed no HR rows, so `measured_max_hr` hits the empty-corpus D3 fallback → `new_max_hr == current` → `rederive_zones` still returns `changed=False`; no behavioral change. `records.value` NULLs are correctly ignored by both `func.max` and the `>= floor` filter.
- TASK-003 is feasible: default profile `max_hr=192`, ceiling 205, so a seeded peak (e.g. 198) ratchets up and re-derives `z5.high`; ISO_WEEK `2026-W23` → recompute week `2026-06-01..07`, due when `constants_recomputed_week="2026-W19"`.
- TASK-004 final-validation covers every PLAN Acceptance Criterion (unit props, wiring, end-to-end shift/quiet/artifact, ruff+pytest, D4 parity, cross-repo epic tick).

Net: two substantive fixes (#1 tz-precision over-claim, #2 parity-test fixture scope) before implementation; #3/#4 are cheap cleanups.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | tz-safe `as_of` cutoff over-claims Sofia-precision — a single SQL `func.max()` with a lexical `start_date <` bound and no Python re-filter is device-local-date precise only; "widen like `_window`" is unsound without the paired Python narrowing | high | apply | Grounded in `_window`+`_instant_records` (the widening is only safe paired with Python narrowing, which a `func.max()` can't do); honest fix = conservative-inclusive bound + drop Sofia-precision claim + rewrite R3 test | PLAN.md:Scope, PLAN.md:Risks(R3), TASK-001 |
| 2 | D4 parity test placed in `tests/services/` but the `derive_constants` fixture + `sys.path.insert(scripts)` live only in `tests/scripts/conftest.py` (dir-scoped) — fixture-not-found / ModuleNotFoundError | med | apply | Verified: no `tests/conftest.py`, no pytest `pythonpath`, no `scripts/__init__.py`; the TASK-001 evidence command runs `tests/services` in isolation. Move parity test to `tests/scripts/`, importing app-side constants from `app.services.recompute` | PLAN.md:Decisions(D4), TASK-001 |
| 3 | `recompute.py` module docstring says "Pure: … no DB persistence" but this phase adds a `session`-querying read fn — docstring goes stale/misleading | low | apply | Cheap; add a docstring-update step so the module header reflects the new DB-read query | TASK-001 |
| 4 | Doc drift: 2-arg `measured_max_hr(session, as_of)` shorthand vs real 3-arg signature; PLAN L40 "(`session`/`as_of` already in scope)" — only `session` is in scope, `as_of` is derived from `event.iso_week` | low | apply | Real inconsistency, cheap tidy; prevents an implementer misreading the signature/scope | PLAN.md:Goal, PLAN.md:Scope |

**Vs-request check:** none of the four findings indicate the plan misses what was requested (a runtime measured max-HR anchor source feeding zone rederivation). All are correctness/precision/test-wiring refinements within the stated scope, and #1 is exactly the "tz-safe cutoff correctness" the task asked to verify. All findings are grounded in source the reviewer read directly (no hallucinated symbols). No `AskUserQuestion` needed.
