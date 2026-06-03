# TASK-003: constitution_version surfacing and live-weight injection point

Depends on: TASK-002
Suggested commit: `feat(core): surface constitution_version and live-weight injection seam`

## Goal

Surface `constitution_version` from `profile.yaml meta` for brief stamping, and provide a documented
live-weight injection **seam** (the user-context payload, separate from the system prompt) — without baking
live weight into the rendered constitution.

## Files

- `app/core/constitution.py` — extend:
  - `constitution_version(profile: Profile) -> str` — returns `profile.meta.constitution_version` (the
    stamp E9 records on each brief, e.g. `"v1"`). Thin accessor; no coupling to the brief model.
  - The **live-weight seam** — a documented structure marking where E9 injects live `W` at call time,
    kept distinct from the system prompt. Implement as a small `@dataclass LiveContext` (e.g.
    `live_weight_kg: float`) **and** a documented `build_user_context(profile: Profile, live: LiveContext)
    -> dict` stub that returns the *user-context* payload skeleton and stamps `constitution_version` into
    it — explicitly NOT the system prompt, and explicitly the only place live weight enters. The full
    user-context assembly (readiness, budgets, aggregates, flags) is E9; this is the seam + a docstring
    pointing at E9/LLM.md §2. `render_constitution` keeps taking **only** a `Profile` (no weight arg).
- `tests/core/test_constitution.py` — extend with version + seam tests.

## Acceptance

- [ ] `constitution_version(load_profile()) == "v1"` and equals `load_profile().meta.constitution_version`.
- [ ] **Live weight is not in the system prompt:** `render_constitution(profile)` has signature taking only
      `Profile` (no weight param — assert via `inspect.signature`); the rendered output contains no
      live-weight value injected from a runtime number (render the shipped profile, then assert a
      sentinel live weight like `"83.4"` does not appear because it was never passed in).
- [ ] **The seam exists and carries live weight + the version, not the system prompt:** `build_user_context`
      / `LiveContext` exist; `build_user_context(p, LiveContext(live_weight_kg=83.4))` returns a mapping
      that includes the live weight and `constitution_version == "v1"`, and is a **separate** object from
      the `render_constitution` string (the system prompt). (Seam shape only — full assembly is E9.)

## Steps

### RED
- [ ] Add tests: `constitution_version(load_profile()) == "v1"`; `inspect.signature(render_constitution)`
      has exactly one param (`profile`); `LiveContext(live_weight_kg=83.4)` + `build_user_context(p, …)`
      returns a mapping with the weight and `constitution_version` and the rendered system prompt does not
      contain `"83.4"`.

### GREEN
- [ ] Add `constitution_version`, the `LiveContext` dataclass, and the `build_user_context` seam stub to
      `app/core/constitution.py` with docstrings citing LLM.md §2 (live weight via user context, not the
      prompt) and epic R4/R6.

### REFACTOR
- [ ] Keep the seam minimal (clearly a stub for E9); ensure no path reads live weight from `profile.yaml`;
      docstring states the system prompt and the user context are two distinct payloads.

## Notes

Two separate seams, both from LLM.md §2: (1) **`constitution_version`** (epic R6) stamps which rulebook
snapshot produced a brief — surfaced from `Profile.meta.constitution_version`. (2) **Live weight** (epic R4)
is fed via the **user context**, **never** the system prompt / template — so the seam is the user-context
payload, kept distinct from `render_constitution`'s output, and live weight is never read from `profile.yaml`.
Keep `build_user_context` a documented stub: the real readiness/budgets/aggregates assembly is **E9** (out of
scope) — this task only proves the injection point exists and is wired to the version + live weight.
