# Coach App — Data Model (`app.db` + `profile.yaml`)

> The detailed schema companion to [`ARCHITECTURE.md`](./ARCHITECTURE.md) §3. It pins down
> **exactly what gets saved, where, and why** — column by column. The schema is the physical
> form of the constitution's data contract ([`HEALTH-CONSITTUTION.md`](../../HEALTH-CONSITTUTION.md) §11).
>
> Visual companion: open [`db.html`](./db.html) in a browser — paginated, with inline commenting.
> The **`.md` is the source of truth**; the `.html` is generated from it.

---

## 0. The shape: two databases + one config file

Storage is split by **lifecycle** — never mix disposable build output with durable user state.

```
   profile.yaml   static / monthly-frozen constants (§1, §3) — a file, NOT a table
                  written by the bootstrap + monthly recompute · human-readable · git-diffable

   baseline.db    read-only historical corpus (3.5M records, 2019→2026)
                  regenerated wholesale by build_db.py · NEVER opened at runtime
                       │
                       │  build step: derive constants → profile.yaml
                       │  + seed trailing ~90 days  ┐
                       ▼                            ▼
   app.db   ──────────────────────────────────────────────────────────────  Alembic · WAL
            the ONLY database the running API reads or writes
   ┌─ INGEST  (POST /sync) ───────────────────────────────────────────────────────────┐
   │  records · workouts · workout_statistics · activity_summary                       │
   │  raw HealthKit — mirrors baseline.db + uuid/origin · type-whitelisted · upsert     │
   └───────────────────────────────────────┬──────────────────────────────────────────┘
                                            │  recompute affected days on every sync
                                            ▼
   ┌─ DERIVED  (materialized cache) ──────────────────────────────────────────────────┐
   │  daily_metrics — one row/day: sleep · HRV · RHR · 30d mean+SD · zone-min ·          │
   │                  nutrition intake (kcal/protein/carb/fat/fiber/sodium/water) · readiness │
   │  the 7/28-day rollups (training + nutrition adherence) are windowed sums over this  │
   └───────────────────────────────────────────────────────────────────────────────────┘
   ┌─ COACHING STATE ─────────────────────────────────────────────────────────────────┐
   │  checkins (by date) · strength_tests (by week)        ← inputs (a few taps)       │
   │  plans (by iso_week) · suggestions (by date)          ← brain outputs / brief cache│
   └───────────────────────────────────────────────────────────────────────────────────┘
```

**`app.db` = 9 tables.** No `profile` table — those constants live in `profile.yaml` (§5).
All timestamps are ISO-8601 **TEXT carrying the actual offset HealthKit emits per sample** (it
varies — Europe/Sofia is `+0200` in winter, `+0300` in summer, plus travel). They sort correctly
and stay debuggable. Period keys (`date`, `iso_week`) are derived through the **`Europe/Sofia` tz
database** (DST-aware), never by assuming a fixed offset.

---

## 1. Ingest tables — written by `POST /sync`

Raw HealthKit, structurally **mirroring `baseline.db`** so the 90-day seed is a near-straight copy
(modulo the `uuid`/`origin` additions and the `activity_summary` `date_components`→`date` rename)
and the same aggregate queries run over both. Two additions vs. `baseline.db`: a unique `uuid`
(idempotency) and an `origin` flag (`'seed'` | `'sync'`). Only the **whitelisted types** the
deterministic engine reads are stored — not all of HealthKit:

- **Activity / recovery:** HR, HRV SDNN, RHR, sleep analysis, steps, active energy, basal energy,
  PhysicalEffort/METs, VO₂max, **body mass (body weight)**, running cadence & dynamics.
- **Dietary intake (NEW — logged in a 3rd-party app that writes to HealthKit):** dietary energy
  consumed, protein, carbohydrates, fat (total), fiber, sodium, water. These power the nutrition
  intake-vs-target adherence (§2, §7 of the constitution).

> **Body weight comes from HealthKit** (`body_mass` records) like every other measurement. The latest
> `body_mass` is materialized into `daily_metrics.body_weight` and is the **single live-weight source**
> for TDEE/macros — there is no manual weight field on the check-in, so no dedup ambiguity.

### `records` — every sample
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `uuid` | TEXT **UNIQUE** | HealthKit sample UUID → idempotency key. `NULL` for seeded rows. |
| `type` | TEXT NOT NULL | `HKQuantityType…` / `HKCategoryType…` identifier |
| `unit` | TEXT | |
| `value` | REAL | numeric value (quantity types) |
| `value_text` | TEXT | category enums `value` can't hold (sleep stage, stand state) |
| `source_name` · `source_version` · `device` | TEXT | provenance |
| `creation_date` | TEXT | |
| `start_date` | TEXT NOT NULL | |
| `end_date` | TEXT | |
| `origin` | TEXT NOT NULL | `'seed'` (from `baseline.db`) or `'sync'` (live) |

Indexes: `UNIQUE(uuid)` · `(type, start_date)` · `(start_date)`.
Write: `INSERT … ON CONFLICT(uuid) DO NOTHING` (idempotent re-sync).

### `workouts` — sessions
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `uuid` | TEXT **UNIQUE** | idempotency key |
| `activity_type` | TEXT NOT NULL | running / boxing / strength / … |
| `duration` · `duration_unit` | REAL · TEXT | |
| `total_distance` · `total_distance_unit` | REAL · TEXT | |
| `total_energy_burned` · `…_unit` | REAL · TEXT | |
| `effort_score` | REAL | **RPE 1–10** from `WorkoutEffortScore` (nullable; used when present) |
| `physical_effort` | REAL | METs proxy — HR-independent intensity, always available (nullable) |
| `source_name` · `source_version` · `device` · `creation_date` | TEXT | |
| `start_date` | TEXT NOT NULL | |
| `end_date` | TEXT | |
| `origin` | TEXT NOT NULL | `'seed'` / `'sync'` |

### `workout_statistics` — per-workout aggregates
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `workout_id` | INTEGER NOT NULL → `workouts(id)` | FK |
| `type` | TEXT NOT NULL | HR / speed / power / cadence |
| `start_date` · `end_date` | TEXT | |
| `sum` · `average` · `minimum` · `maximum` | REAL | |
| `unit` | TEXT | |

Index: `(workout_id, type)`.

### `activity_summary` — daily Apple Watch rings
| Column | Type | Notes |
|---|---|---|
| `date` | TEXT **PK** | Europe/Sofia date; **upsert by date** |
| `active_energy_burned` · `…_goal` | REAL | |
| `apple_exercise_time` · `…_goal` | REAL | |
| `apple_stand_hours` · `…_goal` | INTEGER | |
| `apple_move_time` · `…_goal` | REAL | |

---

## 2. Derived table — `daily_metrics` (materialized cache)

One row per day, **recomputed whenever that day's source data changes** (i.e. on sync). This is
the single source for the 7/28-day rollups (windowed sums) **and** the rolling readiness baselines.
Chosen over compute-on-the-fly for speed, reproducibility, and a debuggable day-level history.

| Column | Type | Notes |
|---|---|---|
| `date` | TEXT **PK** | Europe/Sofia date |
| `sleep_h` | REAL | last night's asleep hours |
| `hrv_sdnn` | REAL | this-morning HRV (SDNN) |
| `rhr` | REAL | this-morning resting HR |
| `hrv_30d_mean` | REAL | rolling 30-day HRV mean — **readiness baseline** (§6.1) |
| `hrv_30d_sd` | REAL | rolling 30-day HRV SD — needed for the "1 SD below" penalty |
| `rhr_30d_mean` | REAL | rolling 30-day RHR mean — **readiness baseline** |
| `steps` | INTEGER | |
| `active_energy` | REAL | kcal |
| `z1_min` … `z5_min` | REAL | minutes in each HR zone (from `records`) |
| `kcal_in` | REAL | dietary energy consumed (from `records`) — for intake-vs-target adherence |
| `protein_in_g` | REAL | dietary protein consumed |
| `carbs_in_g` | REAL | dietary carbohydrates consumed |
| `fat_in_g` | REAL | dietary fat consumed |
| `fiber_in_g` | REAL | dietary fiber consumed |
| `sodium_in_mg` | REAL | dietary sodium consumed |
| `water_in_l` | REAL | dietary water consumed |
| `body_weight` | REAL | latest `body_mass` (HealthKit) for the day — **the live weight** for TDEE/macros |
| `hard_day` | INTEGER | 0/1 — was it a quality/hard day, **corroborated** against the session's actual intensity (see the note below the table) |
| `readiness_score` | INTEGER | 0–100 (§6.1). Filled by `DAILY_ADJUSTER`; nullable until the daily brief runs |
| `band` | TEXT | `GREEN` / `AMBER` / `RED` |
| `computed_at` | TEXT | |

> `readiness_score` / `band` also get snapshotted onto the `suggestions` row for that date, but
> `daily_metrics` is the canonical per-day series.

> **`hard_day` — the corroborated rule.** `1` if ANY of the day's workouts is hard, decided
> per workout in this order:
>
> 1. duration ≥ **90 min** — the long-session rule, unconditional and never gated;
> 2. **confirmed by either intensity signal, whatever the activity type** — a *valid*
>    `workouts.effort_score` ≥ **7** on a session of ≥ **20 min**, or ≥ **15** minutes of
>    z4+z5 credited **inside that workout's own start–end window** (per workout: minutes
>    earned elsewhere in the day, or by another session, never count);
> 3. otherwise the **activity-type fallback** — `boxing` / `high_intensity_interval_training`
>    / `kickboxing` / `martial_arts` — but ONLY when **both** signals are *absent*.
>
> "Absent" means untrustworthy, not merely null: an `effort_score` outside **1–10** is
> treated exactly as `NULL`, and the zone signal counts as present only when credited
> in-window HR reaches **50 %** of the workout's duration (below that — dead battery,
> manual log — the label's protection stands rather than demoting a real session).
> Promotion by z4+z5 is deliberately *not* coverage-gated. So a threshold/VO₂ run typed
> `running` is now caught, and a HIIT-labelled session the data disproves is not flagged.
> Always a real 0/1, never null. Thresholds live as constants in
> `app/services/daily_metrics_engine.py`; rationale in
> `docs/artifacts/plans/corroborated-hard-day/DECISIONS.md`.

---

## 3. Coaching-state inputs

### `checkins` — the daily check-in (a few objective taps)
Readiness is objective-only (§6.1), so the check-in carries **no** subjective self-report
(energy/soreness/motivation are gone) and the GI check is a **single boolean**, not granular.
**No body-weight field** — weight comes from HealthKit (`body_mass` → `daily_metrics.body_weight`).

| Column | Type | Notes |
|---|---|---|
| `date` | TEXT **PK** | Europe/Sofia date; **upsertable by date** |
| `gi_symptoms` | INTEGER | 0/1 — **any** GI flare sign present (blood / >4 loose stools / urgency / abdominal pain). Feeds the §6.2 safety gate. |
| `illness` | INTEGER | 0/1 — illness / fever → safety-gate rest (§6.2) |
| `knee_pain` | INTEGER | **0–10, 0 = none** — impact-gating flag (§8.2; `>3` → no impact) |
| `created_at` · `updated_at` | TEXT | |

### `strength_tests` — the weekly test (two numbers)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `date` | TEXT NOT NULL | |
| `iso_week` | TEXT NOT NULL **UNIQUE** | one test per week |
| `max_pushups` · `max_pullups` | INTEGER | §9/§10 KPI; trend-smoothing computed, raw stored |
| `created_at` | TEXT | |

---

## 4. Coaching-state outputs (brief cache)

Two tables, not one — the payloads differ enough that shared columns would sit half-empty.
Each caches one brief per period and snapshots the exact inputs it was generated from.

### `plans` — weekly plan (`WEEKLY_PLANNER` output)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `iso_week` | TEXT NOT NULL **UNIQUE** | period key, e.g. `2026-W23` → cache key |
| `payload` | TEXT NOT NULL | JSON: tiered week (core + extras), budgets, weekly targets, **week nutrition (protein/fat/hydration targets + carb day-type pattern + last-week intake adherence)** |
| `rationale` | TEXT | the plan's written reasoning |
| `inputs_snapshot` | TEXT | JSON: the aggregates (training **+ nutrition adherence**) **and constants** the LLM saw (reproducibility) |
| `model` | TEXT | e.g. `claude-opus-4-8` |
| `constitution_version` | TEXT | which rulebook version produced it |
| `created_at` | TEXT | |

### `suggestions` — daily tuned session (`DAILY_ADJUSTER` output)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `date` | TEXT NOT NULL **UNIQUE** | period key, Europe/Sofia date → cache key |
| `readiness_score` | INTEGER | 0–100 (§6.1) |
| `band` | TEXT | `GREEN` / `AMBER` / `RED` |
| `safety_gate_tripped` | INTEGER | 0/1 — did §6.2 short-circuit to REST? |
| `gate_reason` | TEXT | which flag tripped (nullable) |
| `payload` | TEXT NOT NULL | JSON: session + 1–2 alternatives + skip-OK flag + the day's macro focus |
| `inputs_snapshot` | TEXT | JSON: the numbers the LLM saw |
| `model` · `constitution_version` · `created_at` | TEXT | |

> `?refresh=true` deletes the row for the period and regenerates. The `UNIQUE(iso_week)` /
> `UNIQUE(date)` constraints enforce one brief per period.

---

## 5. `profile.yaml` — constants (a file, not a table)

`profile.yaml` is the **single source of truth for every numeric constant.** The athlete profile (§1),
zones (§3), and the nutrition constants (§7) are **config**: set once, refreshed monthly by the
`RecomputeConstants` node (§10). `HEALTH-CONSITTUTION.md` is a **Jinja2 template** whose `{{ … }}`
placeholders are filled from this file at render time, so the rulebook can never drift from it. A YAML
file is the better home than a table — human-readable, hand-editable, git-diffable (free version
history). The **live/derived** values that *look* like profile but move daily stay in the DB.

| Lives in `profile.yaml` (static / monthly-frozen) | Lives in the DB (live / derived) |
|---|---|
| age, sex, `height_cm`, `goal_weight_kg` | **current weight** → latest `body_mass` (HealthKit) → `daily_metrics.body_weight` |
| `max_hr`, `rhr_baseline`¹ | **30d HRV mean+SD, 30d RHR mean** → `daily_metrics` |
| `easy_hr_cap`, `cadence_target_spm`, `cadence_current_spm` | per-day sleep / zone-minutes / readiness → `daily_metrics` |
| `zones` (Z1–Z5 bpm bounds) | per-day nutrition intake → `daily_metrics` |
| `nutrition` (activity factor, deficit %, protein/fat g/kg, carb multipliers, hydration, fiber) | |

¹ `rhr_baseline` / `hrv_baseline` here are the **monthly-frozen anchors used to derive zones**.
The **readiness score reads the live rolling values from `daily_metrics`**, not these — so there's
one rolling baseline, not two competing ones.

```yaml
# profile.yaml — the SINGLE SOURCE for constants. Written by the bootstrap step + monthly
# RecomputeConstants (§10). HEALTH-CONSITTUTION.md renders its {{ }} placeholders from here.
athlete:
  age: 34
  sex: male
  height_cm: 174
  goal_weight_kg: 75
thresholds:
  max_hr: 195                # robust corpus max (isolated >205 bpm artifacts dropped)
  rhr_baseline: 58           # monthly anchor for zone derivation
  hrv_baseline_ms: 38        # informational; readiness uses rolling daily_metrics
  easy_hr_cap: 146           # Maffetone 180 − age
  cadence_target_spm: 172    # the END target of the ramp
  cadence_current_spm: 160   # THIS month's cue; RecomputeConstants ramps it +5 toward target
zones:                        # bpm bounds, from compute_zones.py
  z1: [98, 127]
  z2: [127, 152]
  z3: [152, 170]
  z4: [170, 179]
  z5: [179, 195]
nutrition:                    # §7 constants — the macro engine reads these
  activity_factor: 1.65       # TDEE multiplier (very high NEAT)
  deficit_pct: 0.12           # modest deficit for slow recomp (hard cap 0.20)
  protein_g_per_kg: 1.8       # constant daily (kidney-stone cap 2.0)
  fat_g_per_kg_low: 0.8
  fat_g_per_kg_high: 1.0
  carbs_g_per_kg: { hard_low: 4, hard_high: 5, moderate: 3, rest_low: 2, rest_high: 2.5 }
  hydration_l_low: 3.0
  hydration_l_high: 3.5
  fiber_g_low: 25
  fiber_g_high: 35
meta:
  derived_from: baseline.db
  computed_at: 2026-06-02
  constitution_version: v1
```

---

## 6. Write paths & bootstrap

**Who writes what:**

| Trigger | Writes |
|---|---|
| `POST /sync` | `records` / `workouts` / `workout_statistics` (upsert by `uuid`), `activity_summary` (by date), `checkins` (by date), `strength_tests` (by week) → then **recompute `daily_metrics`** for affected dates |
| `POST /brief/weekly` | `plans`; may rewrite `profile.yaml` when constants are stale (§10) |
| `POST /brief/daily` | `suggestions` (+ `readiness_score`/`band` back to `daily_metrics`) |

**Bootstrap (one-time, at deploy)** — an offline build step:
1. derives constants from `baseline.db` → writes **`profile.yaml`**;
2. copies the **trailing ~90 days** of whitelisted samples from `baseline.db` into the ingest
   tables with `origin = 'seed'` → so the first `/brief/weekly` has valid 7/28-day rollups and
   30-day baselines on day one.

After bootstrap, `app.db` grows from `/sync` forward and `baseline.db` is never consulted again.

---

## 7. Decisions & open items

**Decided (with rationale):**

| # | Decision | Why |
|---|---|---|
| 1 | **Two DBs, split by lifecycle** | `build_db.py` does `DROP TABLE …` every run; durable state can't live in a regenerable artifact. |
| 2 | **Ingest = raw records, mirroring `baseline.db`** (+ `uuid`/`origin`) | trivial 90-day seed; same aggregate queries over both DBs; least divergence. |
| 3 | **`daily_metrics` materialized** (not computed inline) | speed, reproducibility, debuggable day-level history; rollups = windowed sums. |
| 4 | **Two brief tables** (`plans` + `suggestions`) | payloads differ (weekly plan vs daily session + readiness/gate); shared columns would sit empty. |
| 5 | **Constants in `profile.yaml`, not a table** | config-shaped, monthly-frozen, human-editable, git-versioned; live weight + rolling baselines stay in the DB. |
| 6 | **`profile.yaml` is the single source; the constitution is a Jinja2 template** | numbers exist in exactly one place. `HEALTH-CONSITTUTION.md`'s `{{ … }}` placeholders render from `profile.yaml`, so the rulebook can't drift. §10 recompute rewrites `profile.yaml` only. *(Resolves the former drift open-item.)* |
| 7 | **Check-in is objective-only + single GI boolean** | readiness is physiological (§6.1); dropped energy/soreness/motivation and granular GI; kept `gi_symptoms`/`illness`/`knee_pain` only. Knee is `0–10` (0 = none). |
| 8 | **Dietary intake *and* body weight come from HealthKit** | food is logged in a 3rd-party app → HealthKit; weight is a `body_mass` record. Both ingest as `records` (closing the nutrition loop). Latest `body_mass` → `daily_metrics.body_weight` is the single live-weight source — no manual field, no dedup. |

**Open items (defaults proposed, not locked):**

- **Seed↔sync overlap.** Seeded rows (`origin='seed'`, `uuid=NULL`) can overlap the first live
  sync's date range. Proposed: live `'sync'` rows are authoritative; a one-time reconciliation
  drops `'seed'` rows for any day fully covered by synced data. *Needs a decision.*
- **Type whitelist exact list.** The activity + dietary types are sketched in §1; finalize the
  precise `HK…Identifier` set (incl. `HKQuantityTypeIdentifierDietary*`) before the first migration.
