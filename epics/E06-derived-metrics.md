# E6 — Derived Metrics Engine (`daily_metrics`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E5 |
| **Unblocks** | E8, E10, E11 |
| **Primary refs** | [`DB.md`](../docs/architecture/DB.md) §2 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §3, §5.3 |

---

## 1. Summary & goal

Build the **materialized per-day cache** (`daily_metrics`) and the **rolling baselines + 7/28-day
rollups** every brief reads. One row per day, **recomputed whenever that day's source data changes** (on
sync). This is the single source for the windowed rollups and the readiness baselines — chosen over
compute-on-the-fly for speed, reproducibility, and a debuggable day-level history
([`DB.md`](../docs/architecture/DB.md) §2).

## 2. Requirements

- **R1** — A **recompute(date)** routine that rebuilds a day's `daily_metrics` row from source
  `records`/`workouts`: sleep hours, this-morning HRV/RHR, zone-minutes, steps, active energy, nutrition
  intake, body weight, and the `hard_day` flag ([`DB.md`](../docs/architecture/DB.md) §2 columns).
- **R2** — **Nutrition intake** aggregated from dietary `records`: `kcal_in`, `protein_in_g`, `carbs_in_g`,
  `fat_in_g`, `fiber_in_g`, `sodium_in_mg`, `water_in_l` ([`DB.md`](../docs/architecture/DB.md) §2).
- **R3** — **Body weight** = the latest `body_mass` for the day → `daily_metrics.body_weight`, the single
  live-weight source for TDEE/macros ([`DB.md`](../docs/architecture/DB.md) §1 note, §2).
- **R4** — **Rolling baselines**: `hrv_30d_mean`, `hrv_30d_sd`, `rhr_30d_mean` — the readiness baselines
  (the rolling values, not the monthly `profile.yaml` anchors)
  ([`DB.md`](../docs/architecture/DB.md) §2, §5 footnote ¹).
- **R5** — **7/28-day rollups** as windowed sums over `daily_metrics` for **training load** and
  **nutrition-intake adherence** (consumed vs target), shaped as the aggregates fed to the LLM context
  ([`DB.md`](../docs/architecture/DB.md) §2; [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5.3).
- **R6** — `readiness_score`/`band` columns are **filled later** by the daily brief (E11) and are nullable
  until then ([`DB.md`](../docs/architecture/DB.md) §2 note).

## 3. What to implement (by phase)

### E6·P1 — Per-day recompute
- `recompute(date)` building the full row except readiness (E11) — sleep/HRV/RHR, **zone-minutes from HR
  records**, steps, active energy, nutrition intake, latest body weight, `hard_day`.
- Idempotent upsert into `daily_metrics`; `computed_at` stamp.
- Driven by E5's recompute hook (recompute every affected date).

### E6·P2 — Rolling 30-day HRV/RHR baselines
- Compute `hrv_30d_mean`, `hrv_30d_sd` (SD needed for the "1 SD below" readiness penalty) and
  `rhr_30d_mean` over the trailing 30 days.
- Write them onto the day's row so readiness (E8/E11) reads one rolling baseline.

### E6·P3 — 7/28-day rollups
- Windowed-sum queries over `daily_metrics` for 7- and 28-day **training** rollups and **nutrition
  adherence** rollups.
- Expose them in the shape `LoadAggregatesNode` (E10) and the daily context (E11) consume.

## 4. Acceptance criteria

- [ ] After a sync touching day D, `recompute(D)` produces a `daily_metrics` row whose sleep/HRV/RHR,
      zone-minutes, nutrition intake, steps, energy, body weight, and `hard_day` match the source rows.
- [ ] Re-running `recompute(D)` is idempotent (same inputs → same row, fresh `computed_at`).
- [ ] `hrv_30d_mean/sd` and `rhr_30d_mean` match a hand-computed 30-day window on a fixture.
- [ ] Body weight equals the **latest** `body_mass` of the day (not first/avg).
- [ ] 7/28-day training and nutrition-adherence rollups equal hand-computed windowed sums on a fixture.
- [ ] `readiness_score`/`band` remain null until the daily brief fills them.

## 5. Expected outcome

A trustworthy day-level series plus baselines and rollups — the deterministic inputs E8 turns into
readiness/macros/budgets and the LLM context both briefs are fed.

## 6. Validation

- Fixture-based recompute tests (each metric), idempotency test.
- Baseline math tests (mean/SD/mean) incl. sparse-data edge cases.
- Rollup tests against hand-computed sums; window boundary correctness (Europe/Sofia days).

## 7. Out of scope

The readiness score itself (E8·P1, written back by E11), macro targets (E8·P3), and the brief assembly
(E10/E11). E6 produces **inputs**, not judgments.
