# E3 — Profile & Constitution

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 2 |
| **Depends on** | E1 |
| **Unblocks** | E4, E8, E9 |
| **Primary refs** | [`DB.md`](../docs/architecture/DB.md) §5 · [`LLM.md`](../docs/architecture/LLM.md) §2 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6 |

---

## 1. Summary & goal

Make **`profile.yaml` the single source of truth for every numeric constant**, and render the
**constitution** from it so the rulebook can never drift from the numbers. `profile.yaml` is a file (not a
DB table) — human-readable, hand-editable, git-diffable ([`DB.md`](../docs/architecture/DB.md) §5).
`HEALTH-CONSITTUTION.md` ([`../HEALTH-CONSITTUTION.md`](../HEALTH-CONSITTUTION.md)) becomes a **Jinja2
template** whose `{{ }}` placeholders are filled from `profile.yaml` at render time
([`LLM.md`](../docs/architecture/LLM.md) §2).

## 2. Requirements

- **R1** — A **typed loader** for `profile.yaml` with the exact sections from
  [`DB.md`](../docs/architecture/DB.md) §5: `athlete`, `thresholds`, `zones`, `nutrition`, `meta`.
- **R2** — **Validation** of constants: zone bounds monotonic and contiguous; deficit ≤ 0.20 (hard cap);
  protein ≤ 2.0 g/kg (kidney-stone cap); fat low ≤ high; carb multipliers present for each day type
  ([`DB.md`](../docs/architecture/DB.md) §5 yaml block).
- **R3** — Clear separation: **static/monthly-frozen** values live in `profile.yaml`; **live/derived**
  values (current weight, 30d HRV/RHR baselines, per-day metrics) live in the DB and must **not** be read
  from the file ([`DB.md`](../docs/architecture/DB.md) §5 table + footnote ¹).
- **R4** — The constitution renders **fresh each call** (caching off) from `profile.yaml`; live weight is
  injected via the **user context**, not baked into the prompt ([`LLM.md`](../docs/architecture/LLM.md) §2).
- **R5** — The **§2 medical block renders as CONTEXT**, not a code-enforced layer (fitness app, not a
  medical device) ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6; [`LLM.md`](../docs/architecture/LLM.md) §2).
- **R6** — A **`constitutionVersion`** stamp is surfaced so each brief records which rulebook snapshot
  produced it ([`LLM.md`](../docs/architecture/LLM.md) §2; [`MODELS.md`](../docs/architecture/MODELS.md) DailyBrief).

## 3. What to implement (by phase)

### E3·P1 — profile.yaml schema & loader
- Pydantic models for `athlete` / `thresholds` / `zones` / `nutrition` / `meta` mirroring the
  [`DB.md`](../docs/architecture/DB.md) §5 yaml exactly (carb multipliers `{hard_low, hard_high, moderate,
  rest_low, rest_high}`, etc.).
- Loader + validator (R2). Ship the **example `profile.yaml`** from [`DB.md`](../docs/architecture/DB.md)
  §5 as a starting file so downstream epics have constants before E4 generates them for real.
- Helper accessors used by E8 (zones, nutrition constants) and E9 (render inputs).

### E3·P2 — Constitution template & renderer
- Convert `HEALTH-CONSITTUTION.md` into a **Jinja2 template** with `{{ }}` placeholders for maxHR, RHR/HRV
  baselines, zones, cadence cue, and the nutrition constants (activity factor, deficit %, protein/fat g/kg,
  carb multipliers, hydration, fiber).
- Renderer producing the system-prompt string fresh per call; medical block rendered as context.
- Expose `constitution_version` from `profile.yaml meta` for stamping on briefs.

## 4. Acceptance criteria

- [ ] A valid `profile.yaml` loads into the typed model; an out-of-range deficit (>0.20) or protein
      (>2.0), non-monotonic zones, or a missing carb multiplier raises a clear validation error.
- [ ] The renderer fills every `{{ }}` placeholder — a missing constant fails loudly (no silent blanks).
- [ ] Rendered output contains the live constants (e.g. `max_hr`, zone bounds) and the medical block as
      prose context.
- [ ] The loader exposes `constitution_version` and the nutrition/zone constants E8/E9 need.
- [ ] No live/derived value (current weight, rolling baselines) is sourced from `profile.yaml`.

## 5. Expected outcome

A single, validated constants file and a drift-proof rendered constitution — consumed by E8 (math), E9
(system prompt), and E4 (which rewrites the file from `baseline.db`).

## 6. Validation

- Loader unit tests: valid file, each invalid case (caps, monotonicity, missing keys).
- Renderer test: all placeholders filled; snapshot of a rendered section; version surfaced.

## 7. Out of scope

Deriving the constants from `baseline.db` (E4·P2) and the monthly recompute that rewrites the file
(E8·P5 + E10). This epic only **reads/renders**; E4 **generates**.
