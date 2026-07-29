# Decisions — E6·P1 Per-day recompute

Date: 2026-06-04

This file records the two decisions that weighed ≥2 real options (recompute-from-source vs incremental
delta; and source de-duplication for aggregated metrics), plus the two conventions that needed pinning so
implementation and tests agree (null-vs-zero, and the `hard_day` predicate). The remaining decisions live
inline in `PLAN.md` → `## Decisions`.

---

## Decision 1 — Recompute-from-source vs incremental delta

### Options Considered

1. **Recompute-from-source (chosen).** `recompute_day(session, D)` rebuilds the **entire** `daily_metrics`
   row for day `D` from whatever `records`/`workouts`/`activity_summary` rows are currently in `app.db` for
   that Sofia day, then upserts it. The day's metrics are a pure function of that day's stored rows.
2. **Incremental delta.** Track which source rows changed in a sync and adjust the existing `daily_metrics`
   row by the delta (e.g. add the new `step_count` samples to the stored `steps`, splice new zone-minutes).

### Dependencies

- DB.md §2: `daily_metrics` is "recomputed **whenever that day's source data changes**" — a materialized
  cache chosen "for speed, reproducibility, and a debuggable day-level history".
- Epic §4: "Re-running `recompute(D)` is **idempotent** (same inputs → same row, fresh `computed_at`)".
- E5·P3 already fires recompute with the **affected Sofia-date set** post-commit, unconditionally — the
  engine is handed a `set[date]`, not a row-level changelog. Records upsert is `ON CONFLICT(uuid) DO NOTHING`
  (idempotent), so a re-sync can re-present the same samples.
- Single-user, small `app.db` (KB→MB), one synchronous process (ARCHITECTURE §0/§1) — a per-day full
  rebuild over one day's rows is cheap.

### Selected Option

**Option 1 — recompute-from-source.**

### Rationale

- **Idempotency falls out for free.** Same stored rows → same computed columns (only `computed_at` advances),
  which is exactly epic §4's idempotency requirement. An incremental delta would have to be perfectly
  reconciled against re-presented/duplicate samples to stay idempotent — fragile.
- **Self-healing.** A late, corrected, or out-of-order sync (or a future seed↔sync reconciliation, DB.md §7)
  simply re-derives the day from current state; there is no accumulated drift to repair.
- **Matches the seam contract.** E5·P3 hands the engine a `set[date]`, not a per-row delta — recompute-from-
  source is the natural fit; an incremental engine would need a richer (and not-yet-existing) change feed.
- **Reproducible & debuggable** (DB.md §2 rationale): the row is a deterministic function of the day's
  source rows, so it can be re-derived and diffed at any time.
- **Cheap at this scale.** One day's rows over an indexed `(type, start_date)` read is trivial; correctness
  and simplicity dominate a micro-optimization that doesn't matter for a single user.

### Rejected Options

- **Option 2 — incremental delta.** Rejected: it trades the free idempotency and self-healing of a pure
  rebuild for complex delta reconciliation against duplicate/re-presented samples, couples the engine to a
  row-level change feed that the E5·P3 seam does not provide (it passes only dates), and buys no meaningful
  performance at single-user scale. It would also make the "same inputs → same row" acceptance test
  effectively untestable without replaying an exact mutation history.

---

## Decision 2 — Null-vs-zero convention per metric

### Options Considered

1. **No source row → `None` (chosen).** A metric writes `None` when the day has **no** source row of its
   type; a real aggregate (including a genuine `0`) writes the value. Absence and zero are distinct.
2. **No source row → `0`.** Default every metric to `0` when no source rows exist.

### Dependencies

- DB.md §2: every derived column on `daily_metrics` is **nullable** (no `NOT NULL`, no default) — the schema
  is built to distinguish "unknown" from a real value.
- Downstream (E6·P2 baselines, E8 readiness/macros): a 30-day HRV mean must skip days with **no** HRV
  reading, not average a fabricated `0`; a `0` HRV/RHR would corrupt the baseline and readiness penalty.

### Selected Option

**Option 1 — no source row → `None`.**

### Rationale

A fabricated `0` for "no HRV reading" would silently corrupt the rolling baseline (E6·P2) and the readiness
"1 SD below" penalty (E8) — the schema is nullable precisely so absence is representable. Sums over an empty
set are `None` (no data), not `0`; zone-minutes for a day with no HR records follow the same rule. A test
pins this: a day with no HR records yields **null** `hrv_sdnn`/`rhr`/`z*_min`, distinct from a day with a
real zero aggregate.

> Edge note for sums (steps / active_energy / nutrition): a day with **some** dietary records but a genuine
> total of `0` for one nutrient writes `0` (a real aggregate), while a day with **no** dietary records of
> that type writes `None`. The test seeds both to pin the distinction.

### Rejected Options

- **Option 2 — default `0`.** Rejected: erases the absence/zero distinction the nullable schema is built for
  and would corrupt the E6·P2 baselines and E8 readiness math that must skip missing days.

---

## Decision 3 — The `hard_day` predicate

> **Revised by** [`docs/artifacts/plans/corroborated-hard-day/DECISIONS.md`](../../corroborated-hard-day/DECISIONS.md)
> (2026-07-29): the type/duration predicate below is now only the *fallback*, reached when a
> workout carries neither corroborating intensity signal. Rejected Option 2 was partly right —
> effort and zone-minutes do refine the outcome when present, without losing determinism.

### Options Considered

1. **Deterministic predicate over the day's `workouts` (chosen):** `hard_day = 1` if the day has any workout
   whose `activity_type` is in a fixed hard-session set (e.g. boxing / a threshold or VO₂ run / HIIT) **or**
   a workout exceeding a long-duration threshold ("long"); else `0`.
2. **Effort/zone-load scoring:** compute `hard_day` from `effort_score` (RPE), `physical_effort` (METs),
   and/or Z4/Z5 zone-minutes against a tuned threshold.

### Dependencies

- DB.md §2: `hard_day` is "0/1 — was it a quality/hard day (boxing/threshold/VO₂/long/HIIT)" — a flag, with
  the listed categories as **examples**, not a closed scoring rule.
- Epic §3 E6·P1 lists `hard_day` as a per-day flag to set; epic §7 keeps **judgments** (readiness, the
  hard-day **budget**) in E8. `effort_score`/`physical_effort` are **nullable** (DB.md §1) — not always
  present, so a predicate that depends on them is non-deterministic across days.

### Selected Option

**Option 1 — deterministic predicate over `workouts`** (`activity_type` in the hard set, with a
long-duration fallback). **The constants are pinned here** (round-2 #3) so the implementation and tests
agree exactly — `workouts.activity_type` is free TEXT and `duration_unit` varies, so leaving these as
"examples" would let an impl pass the boxing fixture yet silently misclassify the rest:

```python
# Pinned in app/services/daily_metrics_engine.py as named constants.
HARD_ACTIVITY_TYPES = {            # matched case-insensitively against workouts.activity_type
    "boxing",
    "high_intensity_interval_training",   # HKWorkoutActivityType HIIT
    "kickboxing",
    "martial_arts",
}
# A run/ride is "hard" only when it is threshold/VO2 (we cannot infer that from activity_type
# alone, so for E6·P1 those count via the long-duration fallback or a Z4/Z5 presence check);
# refined threshold/VO2 classification is an E8 tuning concern (see Rationale).
LONG_DURATION_MIN = 90.0           # minutes; "long" session fallback, BOUNDARY INCLUSIVE (>=)

def is_hard_day(workouts_for_day) -> int:
    for w in workouts_for_day:
        at = (w.activity_type or "").strip().lower()
        if at in HARD_ACTIVITY_TYPES:
            return 1
        if _duration_minutes(w) >= LONG_DURATION_MIN:   # normalize via w.duration_unit
            return 1
    return 0
```

- **Duration normalization:** `duration` is normalized to **minutes** via `duration_unit` (HealthKit emits
  `s`/`min`; convert `s`→`/60`, pass `min` through, reject/ignore an unknown unit by treating that workout's
  duration as 0 for the threshold — it can still trip via `activity_type`). The threshold is **inclusive**
  (`>= 90 min` is hard).
- **Activity-type match is case-insensitive on the trimmed string** (free TEXT). A run/ride that is
  genuinely threshold/VO₂ but under 90 min is **not** flagged hard by E6·P1's simple predicate — that finer
  classification is deferred to E8 (see Rationale); E6·P1 ships the deterministic, testable flag.

### Rationale

- **Deterministic and always computable.** It reads `activity_type` (always present) + `duration` (always
  present), not the nullable `effort_score`/`physical_effort`, so the flag is well-defined for every day.
- **Testable and stable.** The pinned set + threshold are exercised by a fixture **per hard `activity_type`**
  and at **just-below / at / just-above** the `LONG_DURATION_MIN` boundary (with a unit-conversion case,
  e.g. duration in seconds), plus easy-only / empty → `0`; so a regression or a unit-normalization bug is
  caught. A tuned score would drift and be hard to assert.
- **Right altitude for E6·P1.** The phase ships **inputs**, not judgments (epic §7). A 0/1 flag the LLM/E8
  reads is the input; refined hard-day **scoring** (effort/zone-load weighting) is a later tuning concern and
  belongs with the E8 budget logic, not the per-day cache rebuild.

### Rejected Options

- **Option 2 — effort/zone-load scoring.** Rejected for E6·P1: depends on nullable fields (non-deterministic
  across days), needs a tuned threshold that would drift, and crosses into the judgment E8 owns. The simple
  `workouts`-based predicate is sufficient and testable now; scoring can refine it later without changing the
  `daily_metrics` column.

---

## Decision 4 — Source de-duplication for aggregated metrics

Added 2026-06-04, after a data audit of the seed corpus found per-day **device double-counting** that the
drafted aggregators (blind `SUM` over source rows) would have written into `daily_metrics`.

### Context

`records` deliberately preserves raw, **un-deduped** HealthKit samples with full provenance
(`source_name`/`source_version`/`device`) — E4·P1/P3 are right to keep a faithful corpus; dedup there would
destroy data the aggregation layer needs. But the per-day aggregators in **this** phase must reconcile
multiple sources or they double-count. Audit of the seed corpus:

| Metric | Sources observed | Per-day exposure |
|---|---|---|
| `steps` (`step_count`) | Apple Watch **and** iPhone | **every** recent day — a blind `SUM` ≈ ×2 (~17k/day vs the deduped ~10k that matches Apple Health) |
| `active_energy` (`active_energy_burned`) | Watch, Garmin/Connect, Strava, Nike Run Club … (10 historical) | only ~2/365 days multi-source today — low but nonzero |
| `zone_minutes` (from `heart_rate`) | Apple Watch, Garmin/Connect, Nike Run Club | overlapping samples from a dual-device workout double-count minutes |
| nutrition intake (`dietary_*`) | MacroFactor, MyFitnessPal, YAZIO … | different **apps** hold different **entries** — NOT redundant measurements of one total |

### Options Considered

1. **Blind `SUM` across sources** — what the drafted `steps()`/`active_energy()`/`nutrition_intake()` specified.
2. **Source-priority per Sofia day** (chosen for the device-cumulative metrics) — pick one source per metric
   per day by a fixed priority; aggregate only its rows.
3. **Interval-merge** — merge overlapping sample intervals across sources, count only non-overlapping coverage.

### Selected Option — per-metric, source-aware aggregation

- **Device-cumulative metrics — `steps`, `active_energy`, and the `heart_rate` samples feeding
  `zone_minutes` — Option 2 (source-priority per Sofia day).** For the day, select the single
  highest-priority `source_name` that has any row of the metric's type and aggregate **only that source's**
  rows (steps/active_energy: sum; zone_minutes: bucket only that source's HR samples, then apply the
  existing cross-midnight split). Pinned priority, highest first:

  ```python
  # app/services/daily_metrics_engine.py — pinned, ordered, case-insensitive on the
  # whitespace-normalized source_name (the Apple Watch source carries a NON-BREAKING space, U+00A0).
  def source_rank(source_name: str | None) -> int:   # lower = higher priority
      s = (source_name or "").lower().replace(" ", " ").strip()
      if "apple watch" in s:               return 0   # wrist truth
      if "garmin" in s or s == "connect":  return 1   # Garmin Connect
      if s in THIRD_PARTY_WORKOUT_APPS:    return 3   # strava / nike run club / ntc / …
      return 2                                        # iPhone hostnames & unknown → "phone/other"
  ```

  Selection rule: take `min(source_rank)` present that day; ties **within** a tier broken by the larger
  same-day total, then `source_name` (deterministic). The classifier keys on **capabilities, not hard-coded
  phone hostnames** (`itsonev-ip15` etc. change with every new phone), so it survives a device swap —
  anything unrecognised falls to the rank-2 "phone/other" tier, which the Watch (rank 0) outranks on a
  normal day.

- **`nutrition_intake` — single dominant app per Sofia day.** Group the day's dietary records by
  `source_name`; pick the source with the largest same-day `dietary_energy_consumed` sum (tie-break:
  dietary-record count, then `source_name`); compute **all seven** nutrition columns from **that one
  source's** rows only. **Never** sum a nutrient across sources for the same day. (Different apps hold
  different food entries; same-day multi-source almost always means the day was logged twice during an app
  switch — summing would double-count, and a device-style priority pick would wrongly drop a whole app's
  meals.)

- **Instant picks — `hrv_sdnn`, `rhr`, `body_weight` — unchanged in shape; tie-break by source then
  instant.** They already collapse to one reading; when >1 source offers a same-day reading, prefer the
  higher `source_rank`, then the latest instant (`max parse_ts`). No new double-count exposure.

A shared `pick_source(...)` / `source_rank(...)` helper (reused by the device-metric helpers) implements the
priority; nutrition uses its own dominant-source selector. Decision 2's "no source row → `None`" is
unchanged: if the picked source has rows, its real aggregate (incl. a genuine `0`) is written; a day with
**no** row of the type at all is `None`.

### Rationale

- **Matches how Apple Health itself reconciles** overlapping sources (priority-based source selection). The
  empirical validation that triggered this — picking the best single source per day — reproduced the user's
  Apple Health step count **within ~1%**, where a blind `SUM` overstated steps ~70% and silently inflated the
  NEAT / `activity_factor` that feeds TDEE.
- **Deterministic & idempotent** (Decision 1): same stored rows → same picked source → same row.
- **Metric-aware scope** avoids two traps a steps-only fix would hit: applying device-dedup to **nutrition**
  (which would drop legitimate meal entries) and **missing `zone_minutes`/HR**, which double-counts minutes
  during dual-device (Watch + Garmin) workouts.

### Rejected Options

- **Option 1 (blind `SUM`)** — rejected: the confirmed every-day ×2 step double-count (and the analogous
  active_energy / zone-minute exposure) propagates straight into the E6·P2 baselines, E8 readiness, and the
  macro/TDEE engine. It is the bug this decision exists to prevent.
- **Option 3 (interval-merge)** — rejected for E6·P1: most accurate for a mid-day device switch but
  materially more complex, harder to keep idempotent and unit-testable, and unjustified at single-user scale.
  Revisit only if a metric ever needs sub-day cross-source stitching.

### Tests to pin

- **steps / active_energy:** a day with **both** Apple Watch and iPhone `step_count` rows → equals the
  **Watch-only** sum (not the combined sum); a Watch-absent day with only iPhone rows → falls back to the
  iPhone sum; a genuine `0` from the picked source stays `0`, no row of the type → `None`.
- **zone_minutes:** a day with overlapping Watch + Garmin `heart_rate` samples → minutes from the **priority
  (Watch)** source only (no doubled minutes); the cross-midnight split (round-1 #2) still holds **after**
  source selection.
- **nutrition:** a day logged in **two** apps (MacroFactor + MyFitnessPal) → all seven columns equal the
  **dominant app's** sums (the one with higher `kcal_in`), not the cross-app sum; a single-app day is unchanged.
