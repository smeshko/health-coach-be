# TASK-003: README Local development section

Depends on: TASK-001, TASK-002
Suggested commit: `docs(readme): add Local development section`

## Goal

Add a "Local development" section to `README.md` documenting the clean-checkout `just`-driven flow and what
each recipe does, including which forward recipes depend on E2/E4.

## Files

- `README.md` (repo root, created in E1·P1) — add a `## Local development` section containing:
  - **Prerequisites**: `uv` and `just` installed (Python 3.13 is provided by `uv`); link to `just`.
  - **From a clean checkout — today (E1)** (numbered): `just install` → `just env` (then edit `.env`, set
    `API_TOKEN`) → `just run`, then `curl localhost:8000/health` to confirm. This path completes on the
    current scaffold — it does **not** require `migrate` (no DB tables exist until E2).
  - **Full flow (once E2/E4 land)**: same start, but insert `just migrate` (and optionally `just bootstrap`)
    after `just env` and before `just run`. Documented now so the path is ready; `migrate`/`bootstrap` are
    forward-declared and only fully run after E2/E4 (round-1 #1).
  - **Recipe reference** (table or list), one line each:
    `install`, `run`, `test`, `lint`, `fmt`, `migrate`, `seed`, `bootstrap`, `db-reset`, `env` — each with
    its command and a note of the **owning epic** for forward recipes (`migrate` → E2, `seed`/`bootstrap` →
    E2+E4, so they are not expected to fully run until those epics land).
  - A one-line note that Docker is **not** used for local dev (it's deployment-only, E12).

## Acceptance

- [ ] `README.md` contains a `## Local development` heading.
- [ ] The section documents **two flows**: the E1-now order `just install` → `just env`/set `.env` →
      `just run` → `curl /health` (which completes today, no `migrate`), and the post-E2/E4 full flow that
      inserts `just migrate`/`just bootstrap`.
- [ ] Every recipe (`install`, `run`, `test`, `lint`, `fmt`, `migrate`, `seed`, `bootstrap`, `db-reset`,
      `env`) is listed with a one-line description.
- [ ] The forward recipes (`migrate`/`seed`/`bootstrap`) are annotated with the epic they depend on
      (E2/E4) and that they are not expected to fully run until then.
- [ ] The section states Docker is not needed for local dev (deployment-only, E12).

## Steps

### RED
- [ ] Capture the gap: `grep -n "Local development" README.md` returns nothing and no recipe reference
      exists — the conditions this task closes.

### GREEN
- [ ] Write the `## Local development` section as in **Files**, matching the recipe names/commands in
      `justfile` exactly (no drift).

### REFACTOR
- [ ] Proofread; ensure the recipe table matches the `justfile` 1:1 and the epic annotations are correct;
      `just lint` (which lints the repo, not docs) still passes.

## Notes

Keep the README recipe list in lock-step with `justfile` — a `grep` in final-validation cross-checks that
every recipe name appears in both. The clean-checkout flow assumes E1·P1 (`uv`/entry point) and E1·P2
(`/health`); `migrate`/`seed` are forward-declared and depend on E2/E4 (ARCHITECTURE §1; epic E1·P4).
