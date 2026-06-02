# Coach App — Backend Implementation Epics

> The phased build plan for the backend described in [`docs/architecture/`](./docs/architecture).
> Work is split into **12 epics**, ordered by dependency; each epic is split into **phases** sized for a
> single small-to-medium PR. This file is the **index + status board**. Each epic has a standalone pickup
> doc in [`epics/`](./epics) with full requirements, acceptance criteria, and validation.
>
> Visual companion: open [`docs/architecture/epics.html`](./docs/architecture/epics.html) — paginated,
> with per-phase plan viewers linked in the sidebar.

## Status legend

| Badge | Meaning |
|---|---|
| 🔵 `ready for dev` | scoped and ready to be picked up |
| 🟡 `in progress` | actively being implemented |
| 🟢 `done` | merged and validated |

> **Planning state** (separate from build status): epics **E1–E5** have per-phase plans authored with
> `create-plan` and hardened with `validate-plan`, under [`.claude/plans/`](./.claude/plans). Each plan has
> a single-file HTML viewer linked from `epics.html`. E6–E12 are scoped but not yet planned.

---

## Overview

| # | Epic | Phases | Status | Depends on | Plans |
|---|---|---|---|---|---|
| E1 | [Foundation & API Skeleton](./epics/E01-foundation.md) | 3 | 🔵 ready for dev | — | ✅ planned |
| E2 | [Persistence Layer (`app.db`)](./epics/E02-persistence.md) | 3 | 🔵 ready for dev | E1 | ✅ planned |
| E3 | [Profile & Constitution](./epics/E03-profile-constitution.md) | 2 | 🔵 ready for dev | E1 | ✅ planned |
| E4 | [Baseline ETL & Bootstrap](./epics/E04-baseline-bootstrap.md) | 3 | 🔵 ready for dev | E2, E3 | ✅ planned |
| E5 | [Sync / Ingest (`POST /sync`)](./epics/E05-sync-ingest.md) | 3 | 🔵 ready for dev | E2 | ✅ planned |
| E6 | [Derived Metrics Engine (`daily_metrics`)](./epics/E06-derived-metrics.md) | 3 | 🔵 ready for dev | E5 | — |
| E7 | [Card System (`CARD_META`)](./epics/E07-card-system.md) | 3 | 🔵 ready for dev | E1 | — |
| E8 | [Deterministic Coaching Computations](./epics/E08-coaching-computations.md) | 5 | 🔵 ready for dev | E6, E3 | — |
| E9 | [LLM Brain (shared)](./epics/E09-llm-brain.md) | 2 | 🔵 ready for dev | E3, E7, E1 | — |
| E10 | [Weekly Brief (`POST /brief/weekly`)](./epics/E10-weekly-brief.md) | 3 | 🔵 ready for dev | E9, E8, E6 | — |
| E11 | [Daily Brief (`POST /brief/daily`)](./epics/E11-daily-brief.md) | 3 | 🔵 ready for dev | E9, E8, E6, E10 | — |
| E12 | [Observability & Deployment](./epics/E12-observability-deployment.md) | 3 | 🔵 ready for dev | E10, E11 | — |

**Totals:** 12 epics · 35 phases · 3 endpoints · 9 DB tables.

> **No PDF/embeddings/RAG epic by design** — the architecture explicitly drops Postgres/pgvector/RAG
> (ARCHITECTURE §1 stack note). The `medical-docs/` PDFs are only a build-time source for the
> constitution's medical context, not a runtime extraction pipeline.

---

## Phase boards

Status per phase. Phase IDs are `E<n>·P<m>`.

### E1 — Foundation & API Skeleton
| Phase | Title | Status |
|---|---|---|
| E1·P1 | Project scaffold & config | 🔵 ready for dev |
| E1·P2 | Auth, error envelope & health | 🔵 ready for dev |
| E1·P3 | Workflow engine primitives | 🔵 ready for dev |

### E2 — Persistence Layer (`app.db`)
| Phase | Title | Status |
|---|---|---|
| E2·P1 | DB engine, WAL & Alembic init | 🔵 ready for dev |
| E2·P2 | Ingest tables | 🔵 ready for dev |
| E2·P3 | Derived & coaching-state tables | 🔵 ready for dev |

### E3 — Profile & Constitution
| Phase | Title | Status |
|---|---|---|
| E3·P1 | profile.yaml schema & loader | 🔵 ready for dev |
| E3·P2 | Constitution template & renderer | 🔵 ready for dev |

### E4 — Baseline ETL & Bootstrap
| Phase | Title | Status |
|---|---|---|
| E4·P1 | build_db.py — export.xml → baseline.db | 🔵 ready for dev |
| E4·P2 | Derive constants → profile.yaml | 🔵 ready for dev |
| E4·P3 | 90-day seed + reconciliation | 🔵 ready for dev |

### E5 — Sync / Ingest
| Phase | Title | Status |
|---|---|---|
| E5·P1 | Sync wire models & type whitelist | 🔵 ready for dev |
| E5·P2 | Idempotent upsert services + SyncResponse | 🔵 ready for dev |
| E5·P3 | Check-in & strength-test upsert + recompute hook | 🔵 ready for dev |

### E6 — Derived Metrics Engine
| Phase | Title | Status |
|---|---|---|
| E6·P1 | Per-day recompute | 🔵 ready for dev |
| E6·P2 | Rolling 30-day HRV/RHR baselines | 🔵 ready for dev |
| E6·P3 | 7/28-day rollups | 🔵 ready for dev |

### E7 — Card System (`CARD_META`)
| Phase | Title | Status |
|---|---|---|
| E7·P1 | CARD_META table & enums | 🔵 ready for dev |
| E7·P2 | Derive-don't-emit expansion | 🔵 ready for dev |
| E7·P3 | constraints.py — pure validators | 🔵 ready for dev |

### E8 — Deterministic Coaching Computations
| Phase | Title | Status |
|---|---|---|
| E8·P1 | Readiness score, penalties & bands | 🔵 ready for dev |
| E8·P2 | Safety-gate booleans | 🔵 ready for dev |
| E8·P3 | Nutrition / macro engine | 🔵 ready for dev |
| E8·P4 | Weekly budgets, volume ramp & deload | 🔵 ready for dev |
| E8·P5 | Monthly recompute helpers | 🔵 ready for dev |

### E9 — LLM Brain (shared)
| Phase | Title | Status |
|---|---|---|
| E9·P1 | AgentNode ↔ PydanticAI wrapper | 🔵 ready for dev |
| E9·P2 | Context assembly & validator harness | 🔵 ready for dev |

### E10 — Weekly Brief
| Phase | Title | Status |
|---|---|---|
| E10·P1 | GeneratePlanNode (weekly agent) | 🔵 ready for dev |
| E10·P2 | WEEKLY_PLANNER workflow assembly | 🔵 ready for dev |
| E10·P3 | Endpoint + get-or-generate | 🔵 ready for dev |

### E11 — Daily Brief
| Phase | Title | Status |
|---|---|---|
| E11·P1 | TuneSessionNode (daily agent) | 🔵 ready for dev |
| E11·P2 | DAILY_ADJUSTER workflow assembly | 🔵 ready for dev |
| E11·P3 | Endpoint + get-or-generate | 🔵 ready for dev |

### E12 — Observability & Deployment
| Phase | Title | Status |
|---|---|---|
| E12·P1 | Langfuse tracing | 🔵 ready for dev |
| E12·P2 | Docker + uvicorn | 🔵 ready for dev |
| E12·P3 | litestream backup + runbook + e2e smoke | 🔵 ready for dev |

---

## Dependency order

```
E1 ─┬─ E2 ─┬─ E4
    │       └─ E5 ── E6 ──┬── E8 ──┐
    ├─ E3 ──────────────┬─┘        ├── E10 ── E11 ── E12
    └─ E7 ──────────────┴── E9 ────┘
```

Build front-to-back: **E1–E3** are independent foundations, **E4/E5** unlock data, **E6–E9** build the
brain's two halves (deterministic + LLM), **E10/E11** are the two briefs, **E12** ships it.

---

*Source of truth for scope: [`docs/architecture/`](./docs/architecture). Each epic doc links the exact
sections it is grounded in. Update the status badges here as phases move; the per-phase plan dirs under
[`.claude/plans/`](./.claude/plans) carry the implementation-level detail for E1–E5.*
