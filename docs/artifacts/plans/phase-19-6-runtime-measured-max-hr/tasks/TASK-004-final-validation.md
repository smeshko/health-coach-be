# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for phase-19-6-runtime-measured-max-hr`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] `uv run ruff check` passes with no issues
- [ ] `uv run pytest` (full suite) is green
- [ ] Module/import boundaries respected — no runtime import of `scripts/derive_constants.py` from `app/` (D4); the app-side `_HR_FLOOR`/`_HR_CEILING` parity test passes
- [ ] Manual smoke: seed a temp `app.db` with an HR peak above the current anchor, drive `RecomputeConstants` on a due week, confirm the re-derived `zones.z5.high` equals the peak (log/pytest excerpt)
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced (test output, log) — no criterion ticked on "the code looks right"

### Epic update — cross-repo (epic doc lives in the iOS repo, NOT here)

This is a standalone backend plan; `PLAN.md`'s `Epic:`/`Phase:` were set by hand and
`link_plan.py` was intentionally NOT run (it cannot cross repos). At phase completion,
update the epic in the **iOS** repo manually:

- [ ] In the iOS repo, tick Phase 19.6's `### Acceptance criteria` in
      `docs/artifacts/epics/19-trustworthy-numbers.md` and point its `**Plan**:` line at
      this backend plan (mark status done).
- [ ] Update the epic's row in the iOS repo's `docs/artifacts/epics/EPICS.md` as
      appropriate (mirrors the 19.4/19.5 completion pattern).
