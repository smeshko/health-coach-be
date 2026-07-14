# Adversarial Validation — Round 2

**Run:** 2026-07-14 04:21 UTC
**Plan:** phase-19-6-runtime-measured-max-hr
**Status at start:** planned
**Prior rounds in scope:** validation/round-1.md
**Reviewer:** independent general-purpose subagent (Codex unavailable for this target — the
plan dir is gitignored, so `--scope working-tree` sees nothing; same fallback as round 1).

## Codex output

<!-- Verbatim independent-reviewer output below. Do not edit. -->

I have everything I need. Here is my second-pass validation.

## Round-2 validation — phase-19-6-runtime-measured-max-hr

**Scrutiny of the three big questions — all CLEAN:**

- **Double-margin / off-by-one (item 1): sound, not a bug.** TASK-002 passes `as_of = _iso_week_monday(event.iso_week) + 7d` (next Monday); `measured_max_hr` adds +1 → bound = next-Tuesday date-prefix, filter `start_date < bound`. That includes device-local prefixes through next-Monday — which is *exactly* the window needed to catch a Sofia-in-week Sunday peak whose device prefix rolls to Monday (the ≤+1-day device/Sofia skew). Passing Sunday instead would *drop* that peak, so next-Monday is required, not an over-margin. TASK-003 seeds only in-week rows, so no assertion is affected. Internally consistent across PLAN Scope/R3/Acceptance and TASK-001 GREEN.
- **Parity test relocation (item 2): correct.** `tests/scripts/conftest.py` really provides the `derive_constants` fixture (L52-55) and `sys.path.insert(0, scripts/)` (L26-27); `derive_constants` exports `HR_FLOOR=80.0`/`HR_CEILING=205.0` (L67-68); `app.services.recompute` is importable from anywhere (`scripts` resolves as a namespace package from repo root). PLAN D4, RESEARCH, TASK-001 all now say tests/scripts — no lingering tests/services placement.
- **TASK-004 coverage (item 3): complete.** Every PLAN acceptance criterion (unit props incl. conservative-inclusive bound, wiring, end-to-end shift/quiet/artifact, ruff+pytest, D4 parity, cross-repo epic tick) maps to a TASK-004 step.

I agree with all four round-1 triage decisions. The findings below are **residuals from incompletely-applied edits** plus minor gaps — no disagreement with the triage itself.

**Findings (most severe first):**

1. **`tz-safe cutoff` survives in PLAN Scope tests-bullet — MED — apply.** PLAN.md L49 still lists `"tz-safe cutoff"` as a unit-test property, directly contradicting the rewritten as_of bullet (L35, "NOT Sofia-precise") and R3. This re-opens the exact trap round-1 #1 closed: an implementer reads "tz-safe cutoff" and writes a Sofia-precise boundary test that can't pass. Round-1 #1's "Scope tz-safe bullet" fix updated only the as_of paragraph, not this enumeration. Fix: rename to "device-local-date / conservative-inclusive cutoff." File: PLAN.md L49.

2. **RESEARCH.md still frames the cutoff as tz-safe — LOW/MED — apply.** RESEARCH L24 ("Used for tz-safe date handling") and L45-48 ("`_window` … the precise Sofia-date filter runs in Python. This is the convention for the tz-safe `as_of` cutoff") describe the widen+Python-narrow convention that the plan now *explicitly rejects*. Round-1 #1 was applied to PLAN+TASK-001 but not RESEARCH, so the research note misleads toward the debunked design. Fix: note the chosen device-local-date bound and that `_window`'s Python-narrowing is deliberately NOT followed. File: RESEARCH.md L24, L45-48.

3. **Stale `app.core.time` import instruction — LOW — apply.** TASK-001 Files (L19) still says import "a date helper from `app.core.time`." After Sofia-precision was dropped, the query needs only `datetime.timedelta` on the passed-in `date` (`(as_of + 1d).isoformat()`); nothing in `app.core.time` (to_sofia/parse_ts) is used. Could nudge the implementer to reintroduce tz handling. File: TASK-001 L19.

4. **2-arg signature residual from #4 — LOW — apply-if-touching.** `measured_max_hr(session, as_of)` still appears in TASK-001 title (L1) and PLAN task-list (L150), vs the 3-arg `(session, as_of, current_max_hr)` everywhere else. Round-1 #4 updated only PLAN Goal/Scope. Cosmetic. Files: PLAN.md L150, TASK-001 L1.

5. **Cutoff exclusion side untested — LOW — apply or defer.** The `as_of` boundary unit test (TASK-001 L37-39, Acceptance) asserts only "an in-week peak is never dropped" (inclusion). No case seeds a *higher out-of-window/future* peak and asserts it's excluded — so an implementation that omits the `.where(start_date < bound)` clause entirely passes every described test, yet the plan (TASK-002 Acceptance) claims "far-future rows excluded." Immaterial in production (no future HR data), but tighten the boundary case to seed a higher future peak and assert it's not the result. File: TASK-001.

6. **Parity test has no task-level evidence — LOW — apply or defer.** TASK-001 Evidence runs `pytest tests/services/test_recompute.py -k measured_max_hr`, which cannot exercise the parity test now living in `tests/scripts/`; the parity assertion required by TASK-001 Acceptance is only demonstrated at TASK-004 (full suite). Add a `tests/scripts` evidence line to TASK-001. File: TASK-001 L43.

**Net:** Substantively the plan is sound — the round-1 fixes are semantically correct and the design is internally consistent. The remaining issues are all documentation residue from partially-applied edits (F1/F2/F4) plus two minor test-adequacy gaps (F5/F6). F1 is the one worth fixing before implementation because it literally re-states the misleading "tz-safe" term round-1 set out to remove.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | "tz-safe cutoff" still listed in PLAN Scope Tests bullet — contradicts the rewritten cutoff design/R3 | med | apply | Real residual; re-opens the round-1 #1 trap. Reworded to "conservative-inclusive `as_of` cutoff (inclusion AND far-future exclusion)" | PLAN.md:Scope(Tests) |
| 2 | RESEARCH.md still frames the cutoff as tz-safe (widen+Python-narrow convention the plan now rejects) | med | apply | Research must not point the implementer at the debunked design; added the validation decision note | RESEARCH.md (time.py bullet + start_date-lexical bullet) |
| 3 | TASK-001 Files still says import "a date helper from `app.core.time`" — no longer used | low | apply | Only `datetime.timedelta` needed; removing avoids reintroducing tz handling | TASK-001:Files |
| 4 | 2-arg `measured_max_hr(session, as_of)` residual in TASK-001 title + PLAN task-list | low | apply | Cosmetic consistency with the 3-arg signature | PLAN.md:Tasks, TASK-001:title |
| 5 | Boundary test asserts inclusion only; nothing guards the `start_date < bound` clause (far-future exclusion) | low | apply | A test-adequacy gap — added assertion (b): a higher far-future peak is excluded | PLAN.md:Scope, TASK-001:Acceptance |
| 6 | Parity test (now in tests/scripts) has no task-level evidence command | low | apply | Added a `tests/scripts/test_derive_constants.py` evidence line to TASK-001 | TASK-001:Evidence |

**Vs-request check:** all six are documentation-consistency / test-adequacy residue of the round-1 edits; none change scope or indicate a missed request. All grounded in files the reviewer read. No `AskUserQuestion` needed.
