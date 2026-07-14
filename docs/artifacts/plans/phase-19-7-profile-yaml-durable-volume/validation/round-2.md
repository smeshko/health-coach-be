# Adversarial Validation — Round 2

**Run:** 2026-07-14
**Plan:** phase-19-7-profile-yaml-durable-volume
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md
**Reviewer:** subagent (Codex unavailable — `docs/` gitignored; documented fallback, clean general-purpose subagent)

## Codex output

<!-- reviewer: general-purpose subagent, verbatim below -->

I've read the round-1 record, all current plan files, and grounded every claim against the actual source (`tests/core/test_profile.py`, `app/core/profile.py`, `Dockerfile`, `docker-entrypoint.sh`, `.env.docker.example`, `RUNBOOK.md`).

## Verdict: the three round-1 edits are sound. No new material defect.

**Edit-verification (all three hold up):**

1. **TASK-003 reframe (strengthen L621, not add).** Verified against the real file: `test_write_profile_default_path_honours_env_override` at L621-627 does exactly what the edits claim (sets `PROFILE_PATH`, no-arg `write_profile`, asserts file at env path, reads back via no-arg `load_profile`, `constitution_version`-only). Every cited line is accurate — L472, L489 (uses `/data/profile.yaml`), L513, L584, L621, and the autouse `_clear_profile_path_env` fixture at L81-85. The two proposed deltas (full-`Profile` equality + anchor-not-written) are genuinely new vs. the existing assertion. Internally consistent.

2. **TASK-005 no-daemon grep (AC#1).** The applied command is `grep -n 'PROFILE_PATH=/data/profile.yaml' Dockerfile` — with **no `ENV ` prefix**. The real ENV block (L61-62) is a multi-line continuation (`ENV APP_DB_PATH=/data/app.db \` / `HOME=/app`), so TASK-001 will insert `    PROFILE_PATH=/data/profile.yaml \` as a continuation line that does **not** contain the literal token `ENV`. The bare-substring grep matches it regardless — so the edit is correctly robust to the formatting TASK-001 produces (it dropped the `ENV` anchor that finding #2's literal suggestion had). The `COPY .*profile.yaml` grep matches L42. Good.

3. **TASK-005 AC#4 docs-diff step.** Concrete `git diff RUNBOOK.md .env.docker.example` step added; grounded against the real stale comment at `.env.docker.example` L28 and `RUNBOOK.md` §5 header at L152. Good.

**Anchor-not-written safety (the prompt's key concern):** Safe as written. The repo-root `profile.yaml` anchor (`app.core.profile.PROFILE_PATH`, 774 B, exists) is only ever **read** for a before/after content-or-mtime comparison — the plan frames it as "still its committed content / mtime unchanged" (read-only). Crucially, TASK-003's RED step (L45-47) chooses the safe variant — *mutate the assertion* (assert anchor WAS written / equality vs. a mutated `Profile`), not break the source — so the write always resolves to `tmp_path` and the real file is never written or deleted. And this is not a new risk: the pre-existing L621 test already calls no-arg `write_profile` under the override. Implementable and non-destructive.

## Findings

1. **Minor wording nit in TASK-005 AC#1 step** — low — **defer**. The step says the grep "shows the `ENV` line", but with the multi-line block the matched line is a continuation (`    PROFILE_PATH=… \`) that lacks the literal `ENV` token. The command still succeeds; only the prose is loose. Optional: reword to "shows the `PROFILE_PATH` env-var line (a continuation of the `ENV` block)". Not worth blocking.

2. **Defer #4 (one-time cutover) — affirm.** Agree with round 1: the `[ ! -f ]` guard no-ops on a pre-placed file and `?refresh=true` re-writes current constants; the RUNBOOK cutover note (TASK-004 L47-52) is the right home. Sound.

3. **Defer #5 (seed safety under `set -eu`/non-root) — affirm.** Confirmed `docker-entrypoint.sh` is `set -eu` (L13), alembic at L22, seed slots before `exec`; subprocess `sh …/seed_profile.sh` isolates the guard. Sound.

Nothing new surfaced beyond the low-severity wording nit. All line-number citations across RESEARCH/PLAN/TASK-003/TASK-005 are current and accurate; no stale cross-reference, contradiction, or dependency issue was introduced by the edits. The plan is ready to implement.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-005 AC#1 grep step prose calls the matched line "the ENV line" — it is a continuation line with no literal `ENV` token | low | apply | Trivial one-line clarity fix; cheap to correct so no inaccuracy carries into implementation | TASK-005 |
| 2 | Round-1 #4 (cutover mitigation) affirm | n/a | reject (affirm) | Reviewer agrees the mitigation is sound and correctly homed in TASK-004 | — |
| 3 | Round-1 #5 (seed `set -eu`/non-root safety) affirm | n/a | reject (affirm) | Reviewer re-confirmed against docker-entrypoint.sh | — |

Round 2 produced no new material defect. The single low-severity wording nit was applied for clarity; no round 3 required.
