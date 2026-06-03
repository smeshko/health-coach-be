# E1 — Foundation & API Skeleton

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 4 |
| **Depends on** | — (bedrock) |
| **Unblocks** | E2, E3, E5, E7, E9 |
| **Primary refs** | [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1, §5 · [`MODELS.md`](../docs/architecture/MODELS.md) "Conventions", "Errors" · [`LLM.md`](../docs/architecture/LLM.md) §0 |

---

## 1. Summary & goal

Stand up the **runnable, authenticated FastAPI process** and the **workflow engine** that every later
epic plugs into — with **no business logic yet**. This is the bedrock: the app factory, typed settings,
the single-token auth, the one error envelope, the camelCase Pydantic base, and the kept Launchpad
`core/` primitives (`Node` / `RouterNode` / `AgentNode` / `TaskContext`).

We build on Datalumina's GenAI Launchpad boilerplate (`../genai-launchpad-main`) but keep **only** its
FastAPI app, the `core/` workflow primitives, PydanticAI, Jinja2, and Alembic. Postgres/pgvector, Celery,
Redis, Supabase, streaming, and `vecs`/RAG are **not** used and must not be carried over
([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 stack note).

## 2. Requirements

- **R1** — A single synchronous FastAPI process launchable with `uvicorn`; no background workers, no
  scheduler, no Celery/Redis ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1).
- **R2** — Typed settings loaded from environment (API token, `app.db` path, model id, Langfuse keys,
  constitution version). One config object, validated at startup.
- **R3** — **Single long-lived bearer token** in the `Authorization` header; never in the body. Single
  user, no tenancy ([`MODELS.md`](../docs/architecture/MODELS.md) Conventions → Auth).
- **R4** — One **error envelope** for all non-2xx with stable machine codes
  ([`MODELS.md`](../docs/architecture/MODELS.md) Errors): `validation_error`, `unauthorized`, `not_found`,
  `brief_generation_failed`, `upstream_timeout`, `internal_error` (named fallback for unmapped statuses /
  unhandled exceptions).
- **R5** — A **camelCase wire / snake_case Python** Pydantic base via `alias_generator`
  ([`MODELS.md`](../docs/architecture/MODELS.md) Conventions → Casing).
- **R6** — The `core/` workflow engine: a DAG of nodes over a shared Pydantic `TaskContext`, node types
  `Node` / `RouterNode` / `AgentNode`, with a `stop_workflow()` short-circuit
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Orchestration, §5 node legend;
  [`LLM.md`](../docs/architecture/LLM.md) §0).
- **R7** — Project layout that the later epics assume: `api/`, `core/`, `database/`, `services/`,
  `tests/`, managed with `uv` on Python 3.13.

## 3. What to implement (by phase)

### E1·P1 — Project scaffold & config
- `uv` project, pinned **Python 3.13**, dependency manifest (FastAPI, uvicorn, pydantic, pydantic-settings,
  SQLAlchemy, Alembic, PydanticAI, Jinja2 — no Postgres/Celery/Redis deps).
- FastAPI **app factory** + `uvicorn` entry point.
- Typed **settings** module (`pydantic-settings`) reading env; fail fast on missing required vars.
- **camelCase Pydantic base model** (`alias_generator=to_camel`, `populate_by_name=True`).
- Directory skeleton: `api/`, `core/`, `database/`, `services/`, `tests/`.

### E1·P2 — Auth, error envelope & health
- Bearer-token auth dependency comparing against the configured token; `401` → `unauthorized` envelope.
- Exception handlers mapping validation / not-found / generic errors to the `Error { code, message, detail }`
  envelope.
- `GET /health` (unauthenticated) returning process liveness + `serverTime`.

### E1·P3 — Workflow engine primitives
- Port/verify `core/`: `TaskContext` (shared Pydantic state), `Node` (deterministic), `RouterNode`
  (conditional branch / short-circuit), `AgentNode` (LLM placeholder — real wiring in E9).
- A `WorkflowRunner`/executor that walks the node graph and honors `stop_workflow()`.
- Tests: linear flow, router branch, early stop.

### E1·P4 — Local dev runner (`justfile`)
- A **`justfile`** giving turnkey local-dev recipes so the app runs without Docker (which is deployment-only,
  E12·P2) and without memorising commands: `install` (`uv sync`), `run` (`uv run uvicorn app.main:app
  --reload`), `test`, `lint`, `fmt` — with bare `just` listing recipes.
- **Forward-declared lifecycle recipes** that shortcut commands arriving in later epics: `migrate`
  (`alembic upgrade head`, E2), `seed` (the bootstrap scripts, E4), `bootstrap` (chain
  install→migrate→seed), `db-reset`. Present now; they light up as their epics land.
- A `.env.example` and a `just`-driven `.env` bootstrap, plus a **README "Local development"** section
  documenting the workflow. (This is local-dev ergonomics; it does not duplicate E12 — no Docker, no
  litestream, no migrate-on-startup.)

## 4. Acceptance criteria

- [ ] `uvicorn` boots the app from a clean checkout following the README steps.
- [ ] `GET /health` returns `200` without auth; a protected probe route returns `401` with the
      `unauthorized` envelope when the token is missing/wrong and `200` when correct.
- [ ] All error responses conform to the single `Error` envelope with a stable `code`.
- [ ] A sample Pydantic model serializes camelCase on the wire and accepts snake_case in Python.
- [ ] A trivial 3-node workflow (Node → RouterNode → Node) runs end-to-end over one `TaskContext`, and a
      `stop_workflow()` in the router short-circuits the rest.
- [ ] No Postgres/Celery/Redis/pgvector imports anywhere in the tree.
- [ ] `just` (no args) lists recipes; `just install`, `just lint`, `just test`, and `just run` work against
      the E1 scaffold; `migrate`/`seed`/`bootstrap` recipes exist and invoke the correct (future) commands.

## 5. Expected outcome

A booting, authenticated FastAPI service with the workflow engine ready — the chassis E2–E12 build on.
Nothing domain-specific yet; the three real endpoints arrive in E5/E10/E11.

## 6. Validation

- Unit tests for auth (missing/invalid/valid token), error-envelope mapping, and the camelCase base.
- Workflow engine unit tests (linear, branch, stop) as above.
- Manual smoke: `uvicorn`, `curl /health`, `curl` a protected route with/without the token.

## 7. Out of scope

DB models (E2), real endpoints (E5/E10/E11), LLM calls (E9), Docker/Langfuse (E12).
