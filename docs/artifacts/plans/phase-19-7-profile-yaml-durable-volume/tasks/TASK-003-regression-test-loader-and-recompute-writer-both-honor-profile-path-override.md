# TASK-003: Regression test: loader AND recompute writer both honor PROFILE_PATH override

Depends on: None
Suggested commit: `test(profile): strengthen the PROFILE_PATH write+load round-trip lock`

## Goal

Strengthen — with a runnable pytest — the existing lock that with `PROFILE_PATH` set, **both**
the no-arg `load_profile()` and the no-arg `write_profile()` resolve to the env path (not the
source-tree anchor), so the durability fix's assumption "recompute writes land on `/data`" can
never silently regress.

**Coverage already exists** (validation round-1 #1): `tests/core/test_profile.py::test_write_profile_default_path_honours_env_override`
(L621-627) already sets `PROFILE_PATH`, calls no-arg `write_profile()`, asserts the file lands at
the env path, and reads it back via no-arg `load_profile()`. The loader half is at L472
(`test_profile_path_env_override_is_honored`) and the `Settings` mirror at L489. So this task is a
**narrow strengthening of the existing L621 test, not a new (duplicate) test**.

## Files

- `tests/core/test_profile.py` — strengthen `test_write_profile_default_path_honours_env_override`
  (L621) in place (or add one tightly-scoped sibling assertion): it is the ONLY change; no source
  edit is expected because `write_profile(path=None)` already routes through `_default_profile_path()`
  (verified: `app/core/profile.py` L323).

## Acceptance

- [ ] The L621 round-trip is strengthened so that, with `monkeypatch.setenv("PROFILE_PATH", str(tmp_path
      / "profile.yaml"))`, no-arg `write_profile(profile)` + no-arg `load_profile()` returns a `Profile`
      **fully equal** to the one written (not just `constitution_version`) — the two share the override.
- [ ] It additionally asserts the source-tree anchor (`app.core.profile.PROFILE_PATH` module constant)
      was **NOT written** (still its committed content / mtime unchanged), proving the override truly
      diverts the write off the anchor. This is the genuinely new coverage delta vs. L621.
- [ ] No duplicate test is introduced — extend/replace L621's assertions rather than add a near-identical copy.
- [ ] Test is green under `uv run pytest tests/core/test_profile.py`.
- [ ] If (contrary to the audit) the writer is found to bypass the override, this task also patches
      `write_profile` to route through `_default_profile_path()` — but this is NOT expected; the audit
      confirms it already does.

Evidence: `uv run pytest tests/core/test_profile.py -q` output showing the strengthened test passing.

## Steps

### RED
- [ ] Add the anchor-not-written assertion to L621 (or a tightly-scoped sibling). To confirm it can
      fail (RED), temporarily assert the anchor WAS written / assert full equality against a mutated
      `Profile`, watch it fail, then correct it.
- [ ] Use the existing `valid_profile_dict()` helper and the `_clear_profile_path_env` autouse fixture
      (L81-85) — set `PROFILE_PATH` explicitly INSIDE the test after the fixture clears it, so the
      assertion is deterministic.

### GREEN
- [ ] With the override already honored in source, the strengthened test passes as written. (Only if a
      real gap surfaces: route `write_profile`'s default through `_default_profile_path()` — not expected.)

### REFACTOR
- [ ] Assert equality via `load_profile() == original` (full `Profile`) to keep the round-trip explicit;
      ensure the temp env is cleaned by monkeypatch teardown.

## Notes

- The autouse `_clear_profile_path_env` fixture (`tests/core/test_profile.py` L81-85) deletes any ambient
  `PROFILE_PATH`; set it explicitly INSIDE the test so the assertion is deterministic.
- No test currently hardcodes `/app/profile.yaml`; `test_shipped_profile_yaml_loads_via_default_path`
  (L423) and L458 use the module `PROFILE_PATH` source-tree anchor and are unaffected by the Docker
  `ENV` — do not touch them. Do not weaken the anchor-not-written assertion into touching those tests.
