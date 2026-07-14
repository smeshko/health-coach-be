# Adversarial Validation — Round 1

**Run:** 2026-07-14
**Plan:** phase-19-7-profile-yaml-durable-volume
**Status at start:** draft
**Reviewer:** subagent (Codex unavailable — `docs/` is gitignored, so `--scope working-tree` sees no diff; used the documented Codex-unavailable fallback: a clean general-purpose subagent with the same adversarial framing)

## Codex output

<!-- reviewer: general-purpose subagent, verbatim below -->

## Adversarial validation — Phase 19.7 (profile.yaml durable volume)

**Axis 1 (vs. codebase): mostly sound.** Every line-number/symbol reference I checked is accurate and current: `profile.py` L30/L33/L51/L286/L307/L323, `weekly.py` L64 + `write_profile(pending)` no-path at L70, `settings.py` L85, `Dockerfile` L42/L55-56/L61/L70/L74, `docker-entrypoint.sh` `set -eu` + alembic L22 / exec uvicorn L25, `.env.docker.example` L28-29, `RUNBOOK.md` §5 L152-170. The four load-bearing claims all hold: load+write share `_default_profile_path()`; the retry wrapper passes no path; the ENV seam is read by `_ProfilePathSettings`; and no test hardcodes `/app/profile.yaml` (tests use the source-tree anchor and `uv run pytest` runs with `PROFILE_PATH` cleared, so the Dockerfile ENV can't perturb them). **One material inaccuracy** (Finding 1).

**Axis 2 (internal coherence): sound on seed-safety, ordering, and cutover; two AC-coverage gaps in TASK-005** (Findings 2, 3). The seed helper is safe under `set -eu` + non-root; entrypoint ordering (after alembic, before `exec`) is fine; the idempotent guard composes correctly with the one-time cutover; dependency graph is sane.

---

### Findings

**1. TASK-003's regression test substantially duplicates an existing test; RESEARCH/PLAN misstate the coverage state.** — severity: high — verdict: **apply**
`tests/core/test_profile.py::test_write_profile_default_path_honours_env_override` (L621-627) already does exactly TASK-003's core: sets `PROFILE_PATH` env, calls `write_profile(...)` with **no path arg**, asserts the file materialized at the env path, then asserts no-arg `load_profile()` reads it back. The loader half is covered by `test_profile_path_env_override_is_honored` (L472), and the Settings-mirror by `test_settings_exposes_profile_path_override` (L489, which even uses `/data/profile.yaml`). RESEARCH.md's "headline finding … only a regression test to lock it" and TASK-003 both fail to acknowledge L621 — TASK-003 references only the L584 round-trip test as its neighbor. The sole genuinely new assertion TASK-003 proposes is "the source-tree anchor was NOT written" (marginal). Rationale: the plan is scoped around adding a test that already exists, risking a near-identical duplicate. Files: `RESEARCH.md`, `PLAN.md` (Research Summary / Scope), `tasks/TASK-003…md` — narrow TASK-003 to the incremental delta (anchor-not-clobbered + full-`Profile` equality vs. the existing `constitution_version`-only assertion) or fold it in, and cite L621.

**2. TASK-005 never verifies AC #1's Dockerfile `ENV PROFILE_PATH=/data/profile.yaml` without a Docker daemon.** — severity: med — verdict: **apply**
AC #1 asserts the runtime file lives on `/data` via the image ENV. TASK-005's concrete steps are pytest + ruff + `profile_seed_smoke.sh`; the only check of the actual ENV wiring is the *optional* `docker_boot_smoke.sh` (needs a daemon). Under done-means-demonstrated, the ENV-value half of AC #1 can go unproven at final validation. Rationale: a trivial non-daemon `grep 'ENV PROFILE_PATH=/data/profile.yaml' Dockerfile` (or the `ENV` block) would close it. Files: `tasks/TASK-005-final-validation.md`.

**3. TASK-005 has no explicit step verifying AC #4 (RUNBOOK §5 + .env.docker.example docs).** — severity: med — verdict: **apply**
TASK-005 lists dedicated steps for AC #2/#3/#5 but none for the docs criterion; only the generic catch-all "all acceptance criteria met" bullet implies it. Given TASK-004's evidence is a `git diff`, TASK-005 should carry a concrete doc-check step so AC #4 isn't ticked on inspection alone. Files: `tasks/TASK-005-final-validation.md`.

**4. One-time cutover mitigation is actionable and composes correctly with the idempotent seed — no defect.** — severity: n/a — verdict: **reject (affirm)**
Pre-placing the live `/app/profile.yaml` (or latest backup) into the `/data` volume before the first 19.7 boot is honored by the `[ ! -f ]` guard (seed no-ops), and the `?refresh=true` fallback re-writes current constants after a stale seed. Both paths are coherent. I note it only to confirm the prompt's concern is unfounded.

**5. Seed step is safe under `set -eu` and non-root, and entrypoint ordering is correct — no defect.** — severity: n/a — verdict: **reject (affirm)**
`mkdir -p` / `[ ! -f ]` / `cp` are all `set -eu`-safe (the test in an `if` doesn't trip `set -e`); subprocess form isolates the entrypoint's `set -eu`/`exec`; `cp` into app-owned `/data` needs no root; a missing seed source fails loudly (intended). `scripts/` ships via Dockerfile L40. Confirmed sound.

**No issues found** with: dependency graph (001→002→004, 003 independent, 005 last), the `.env.docker.example` stale-comment fix (TASK-004 correctly retargets L28 to `/data/profile.yaml`), or the claim that `uv run pytest` is unaffected by the new ENV.

Net: the plan is well-grounded and implementable. Finding 1 is the one worth acting on before implementation (it's the exact duplication the review targeted and it misrepresents existing coverage); Findings 2-3 are small TASK-005 tightenings for done-means-demonstrated.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-003 regression test substantially duplicates existing `test_write_profile_default_path_honours_env_override` (L621); RESEARCH/PLAN misstate coverage as absent | high | apply | Verified independently — L621-627 already round-trips write+load under the env override; plan risks a duplicate and misrepresents the codebase | RESEARCH.md, PLAN.md:Research Summary + Scope, TASK-003 |
| 2 | TASK-005 doesn't verify AC#1's Dockerfile `ENV PROFILE_PATH=/data/profile.yaml` without a Docker daemon | med | apply | Non-daemon `grep` of the Dockerfile closes the ENV-value half of AC#1 for done-means-demonstrated | TASK-005 |
| 3 | TASK-005 has no explicit step for AC#4 (RUNBOOK §5 + .env.docker.example docs) | med | apply | Docs criterion only implied by the catch-all bullet; add a concrete doc-check step | TASK-005 |
| 4 | One-time cutover mitigation actionable + composes with idempotent seed | n/a | reject (affirm) | Reviewer affirms the mitigation is sound; no plan defect | — |
| 5 | Seed step safe under `set -eu` + non-root; entrypoint ordering correct | n/a | reject (affirm) | Reviewer affirms; no plan defect | — |
