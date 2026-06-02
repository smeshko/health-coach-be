# E12 — Observability & Deployment

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E10, E11 |
| **Unblocks** | production |
| **Primary refs** | [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 (deployment/observability/backup) · [`LLM.md`](../docs/architecture/LLM.md) §5 |

---

## 1. Summary & goal

**Trace every LLM call, then ship the single process and its one durable file with continuous backup.**
Langfuse on every brief call (what makes the monthly tuning loop tractable), a single Docker `api`
container running one `uvicorn` process, and `litestream` streaming `app.db`'s WAL to object storage —
plus an end-to-end smoke ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1;
[`LLM.md`](../docs/architecture/LLM.md) §5).

## 2. Requirements

- **R1** — **Langfuse** traces every LLM call: prompt, structured output, retries (incl. `ModelRetry`
  reasons), latency, cost; tagged with `constitutionVersion` + model
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Observability; [`LLM.md`](../docs/architecture/LLM.md) §5).
- **R2** — **One container, one process**: a single `api` Docker container + `uvicorn`, **no** background
  workers/scheduler ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Deployment).
- **R3** — **`litestream`** streams `app.db`'s WAL to object storage continuously so the one durable file
  survives disk loss; document restore ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Backup).
- **R4** — **Access posture documented**: one long-lived API token over HTTPS on a private network /
  Tailscale ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Access).
- **R5** — An **end-to-end smoke** exercising the app-open sequence: `/sync` → `/brief/daily` →
  `/brief/weekly` ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4).

## 3. What to implement (by phase)

### E12·P1 — Langfuse tracing
- Wrap both `AgentNode`s (E9) so every call is traced with prompt/output/retries/latency/cost.
- Tag traces with `constitutionVersion` + model; config via env (keys from E1 settings).

### E12·P2 — Docker + uvicorn
- Dockerfile (uv-based) building a single `api` image running one `uvicorn` process over one `app.db`.
- Run Alembic migrations on start; env-driven config; no workers/scheduler.

### E12·P3 — litestream backup + runbook + e2e smoke
- `litestream` config streaming `app.db` WAL to object storage; documented **bootstrap → deploy →
  restore** runbook (incl. the E4 build step and the access posture).
- An **e2e smoke** test/script: sync sample data → daily brief → weekly brief, asserting `{data,
  narrative}` shapes and cache behaviour.

## 4. Acceptance criteria

- [ ] Every brief LLM call appears in Langfuse with prompt, structured output, retry count + reasons,
      latency, and cost, tagged with model + `constitutionVersion`.
- [ ] `docker build` + `docker run` boots the service (migrations applied) serving the three endpoints from
      one container/process.
- [ ] `litestream` replicates the WAL to the configured target; the runbook restores `app.db` from the
      replica to a working state.
- [ ] The e2e smoke passes end-to-end against a fresh (seeded) DB: `/sync` → `/brief/daily` →
      `/brief/weekly`.
- [ ] The runbook documents bootstrap (E4), deploy, restore, and the HTTPS/Tailscale + token access model.

## 5. Expected outcome

The system is observable, containerised, continuously backed up, and smoke-verified end-to-end — ready to
run for the single user.

## 6. Validation

- Langfuse trace assertion (a call produces a trace with the expected fields) — can use the SDK in a test
  or a manual check documented in the runbook.
- Container boot smoke; litestream replicate+restore drill; the e2e smoke test green.

## 7. Out of scope

Feature work (all in E1–E11). Multi-tenant/scale concerns are explicitly excluded by the single-user
architecture.
