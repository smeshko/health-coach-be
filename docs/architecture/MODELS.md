# Coach App — Request / Response Models

> The HTTP wire contract for the three endpoints in [`ARCHITECTURE.md`](./ARCHITECTURE.md).
> Models are shown as **JSON objects** (the wire format) with a field table each.
>
> Visual companion: open [`models.html`](./models.html) — one page per model, with inline commenting.

---

## Conventions

| Topic | Rule |
|---|---|
| **Casing** | JSON is **camelCase** on the wire (Swift `Codable`-friendly). Python stays snake_case behind a Pydantic `alias_generator`. |
| **Auth** | One long-lived bearer token in the `Authorization` header — never in the body. Single user, no tenancy. |
| **Timestamps** | ISO-8601 carrying **the actual UTC offset the device emits** (Europe/Sofia: `+02:00` winter / `+03:00` summer; travel varies it). Never assume a fixed offset. |
| **Dates** | `YYYY-MM-DD`. **ISO week** keys are `YYYY-Www` (e.g. `2026-W23`). All period keys derived through the **`Europe/Sofia` tz database** (DST-aware). |
| **Refresh** | Brief endpoints take `?refresh=true` as a **query param** (forces regeneration) — it is not a body field. |
| **Nulls vs absent** | Optional fields are sent as `null` or omitted; both mean "not provided". |

### Three design rules behind the briefs

1. **Deterministic / LLM split** ([`ARCHITECTURE.md` §2](./ARCHITECTURE.md)) — the LLM does **no arithmetic**. Readiness, safety-gate booleans, and macro numbers are computed in code; the LLM only picks and tunes within them. So each brief has a strict `*LLMOutput` (what the model may choose) that is merged with deterministic Node output.

2. **Derive-don't-emit** — the `*LLMOutput` types carry **only genuine picks**: which `card`, the `dose` (duration range), `suggestedDay` (weekly), `alternatives`, `skipOk`, the `narrative`, **and the daily `dayType` (see carve-out)**. Every attribute that is a *function of the card* — `intensity`, `zoneTarget`, `isHardDay`, `hrCapBpm`, `cadenceSpm`, `flags` — is **filled in code from `CARD_META`** ([`CARDS.md`](./CARDS.md)) and so **can't be wrong by construction**. The full `SessionBlock`/`PlannedSession` below is the *merged, code-completed* shape the app receives; the model emits the slim `*Pick` subset. This shrinks the model output and collapses most of the validation surface ([`LLM.md` §4](./LLM.md)).

   > **`dayType` carve-out (the one nutrition lever).** `dayType` is *not* derived — the daily LLM **picks** it. Choosing the carb-cycling day type is genuine judgment (decouple fuel from training: deficit push on an easy day, fuel-ahead before a key session), not a function of the card. It **defaults** to the card's `day_type` and is **guarded**: a hard/long session floors it at `hard` (no under-fuelling). Code still computes every macro gram from the chosen `dayType` — the model never emits a number.

3. **Structured `data` vs `narrative`** — every brief response is split into:
   - **`data`** — pure structured payload: enums, numbers, booleans. **Build the UI from this.** It never contains prose.
   - **`narrative`** — an ordered list of LLM-authored `NarrativeSection`s (titles, rationale, coaching tips). **Render this for the user to read.** All human-facing prose lives here and nowhere else.

---

## Enums

| Enum | Values |
|---|---|
| `Zone` | `z1` `z2` `z3` `z4` `z5` |
| `ReadinessBand` | `green` (≥75) · `amber` (50–74) · `red` (<50) |
| `Intensity` | `easy` · `quality` (hard) · `recovery` |
| `DayType` | `hard` · `moderate` · `rest` — nutrition carb-cycling (§7.3) |
| `Tier` | `core` · `extra` |
| `Weekday` | `mon` `tue` `wed` `thu` `fri` `sat` `sun` |
| `NarrativeType` | `summary` · `session` · `nutrition` · `caution` · `plan` |
| `WorkoutCard` | `easy_run` `long_run` `progression_run` `active_recovery` `threshold` `vo2` `strides` `hiit` `jump_rope` `steady_cardio` `strength_push` `strength_pull` `strength_lower` `strength_full` `boxing` `boxing_technique` `foot_prehab` `glute_prehab` `mobility` `rest` |
| `RecordType` | `heart_rate` `heart_rate_variability_sdnn` `resting_heart_rate` `sleep_analysis` `step_count` `active_energy_burned` `basal_energy_burned` `physical_effort` `vo2_max` `body_mass` `running_speed` `running_power` `running_cadence` `running_stride_length` `running_ground_contact_time` `running_vertical_oscillation` `respiratory_rate` · **dietary:** `dietary_energy_consumed` `dietary_protein` `dietary_carbohydrates` `dietary_fat_total` `dietary_fiber` `dietary_sodium` `dietary_water` … *(extensible — new HealthKit types need no schema change. `body_mass` carries body weight, logged via HealthKit; the latest value is the live weight for TDEE/macros.)* |

## NarrativeSection

A unit of LLM-authored coach prose for display. Briefs carry an ordered `narrative: NarrativeSection[]`. **Structured data never contains prose — it all lives here.** The app can render sections in order, or style/place them by `type`.

```json
{
  "type": "session",
  "heading": "Today: easy aerobic run",
  "body": "Keep your average HR at or below 146 — walk the hills if it drifts up. Finish with 6–8 short strides to nudge cadence toward 170."
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | `NarrativeType` | section kind — drives placement / styling in the app. |
| `heading` | string | short title. |
| `body` | string | Markdown / plain prose for display. |

---

# `POST /sync`

Upsert HealthKit samples + the daily check-in (+ optional weekly test). Idempotent by HealthKit `uuid`; check-in/test upsert by date. Payloads are **deltas** (only what's new since the last sync), not the full baseline.

## SyncRequest

```json
{
  "records": [
    {
      "uuid": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "type": "resting_heart_rate",
      "start": "2026-06-02T05:50:00+03:00",
      "end": "2026-06-02T05:50:00+03:00",
      "value": 57,
      "unit": "count/min",
      "category": null,
      "source": "Apple Watch",
      "metadata": null
    },
    {
      "uuid": "9c2b1a77-3e4d-4b21-9f0a-77c1de4488aa",
      "type": "dietary_protein",
      "start": "2026-06-01T13:10:00+03:00",
      "end": "2026-06-01T13:10:00+03:00",
      "value": 38,
      "unit": "g",
      "category": null,
      "source": "MyFitnessPal",
      "metadata": null
    },
    {
      "uuid": "b3f0c211-7a55-4d0e-8e21-1c4488aa9c2b",
      "type": "body_mass",
      "start": "2026-06-02T06:05:00+03:00",
      "end": "2026-06-02T06:05:00+03:00",
      "value": 80.4,
      "unit": "kg",
      "category": null,
      "source": "Withings",
      "metadata": null
    }
  ],
  "workouts": [],
  "activitySummary": [],
  "checkin": {
    "date": "2026-06-02",
    "giSymptoms": false,
    "kneePain": 1,
    "illness": false
  },
  "strengthTest": null
}
```

| Field | Type | Notes |
|---|---|---|
| `records` | HealthRecord[] | default `[]`. |
| `workouts` | Workout[] | default `[]`. |
| `activitySummary` | ActivitySummary[] | default `[]`. |
| `checkin` | DailyCheckin \| null | today's check-in; upsert by date. |
| `strengthTest` | StrengthTest \| null | present on weekly-test days only. |

## HealthRecord

One row in the `records` table. Handles both **quantity** samples (`value` + `unit`) and **category** samples (`category`, e.g. sleep stages).

```json
{
  "uuid": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "type": "heart_rate_variability_sdnn",
  "start": "2026-06-02T06:14:00+03:00",
  "end": "2026-06-02T06:14:00+03:00",
  "value": 38.5,
  "unit": "ms",
  "category": null,
  "source": "Apple Watch",
  "metadata": null
}
```

| Field | Type | Notes |
|---|---|---|
| `uuid` | string (UUID) | HealthKit-assigned `HKObject.uuid` — **read from HealthKit, not generated by the app**. The **idempotency key** (`records.uuid` unique). |
| `type` | `RecordType` | sample kind. |
| `start` / `end` | datetime | equal for instantaneous samples (HR, HRV); a span for sleep. |
| `value` | number \| null | quantity value; `null` for category samples. |
| `unit` | string \| null | HealthKit unit — `count/min`, `ms`, `kcal`, `count`, `kg`, … |
| `category` | string \| null | category value, e.g. sleep stage `asleepDeep` / `asleepREM` / `awake`. |
| `source` | string \| null | producing device / app. |
| `metadata` | object \| null | passthrough extras (running-dynamics details, etc.). |

> **Provenance / why it dedups:** every HealthKit sample has a stable, system-assigned `uuid` (`HKObject.uuid`). The app **reads** it from HealthKit — it does not mint it. The *same physical sample* exports with the *same* `uuid` every time, so re-syncing overlapping date ranges or retrying a failed `/sync` never double-inserts. (App-generated IDs would not have this property.)

## Workout

One row in `workouts` + its `workout_statistics`.

```json
{
  "uuid": "a1b2c3d4-e5f6-4a7b-8c9d-0123456789ab",
  "type": "boxing",
  "start": "2026-06-01T18:30:00+03:00",
  "end": "2026-06-01T19:45:00+03:00",
  "durationS": 4500,
  "distanceM": null,
  "activeEnergyKcal": 720,
  "effortScore": 8,
  "zoneMinutes": { "z1": 5, "z2": 15, "z3": 35, "z4": 15, "z5": 5 },
  "statistics": [
    { "type": "avg_hr", "value": 151, "unit": "count/min" },
    { "type": "max_hr", "value": 189, "unit": "count/min" }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `uuid` | string (UUID) | idempotency key (`workouts.uuid`); HealthKit-assigned. |
| `type` | string | HealthKit activity type — `running`, `boxing`, `functional_strength`, … |
| `start` / `end` | datetime | |
| `durationS` | number | seconds. |
| `distanceM` | number \| null | meters (runs). |
| `activeEnergyKcal` | number \| null | |
| `effortScore` | integer \| null | `WorkoutEffortScore` RPE 1–10 when present (§6 effort/RPE). |
| `zoneMinutes` | object<Zone, number> \| null | minutes per HR zone (§11 data contract). |
| `statistics` | WorkoutStat[] | per-workout avg/max. |

**WorkoutStat** — `{ "type": "avg_hr", "value": 151, "unit": "count/min" }`. `type` ∈ `avg_hr` `max_hr` `avg_speed` `max_speed` `avg_power` `avg_cadence`.

## ActivitySummary

One day of Apple's move / exercise / stand rings.

```json
{
  "date": "2026-06-01",
  "activeEnergyKcal": 1480,
  "exerciseMinutes": 92,
  "standHours": 12,
  "steps": 15230
}
```

| Field | Type | Notes |
|---|---|---|
| `date` | date | upsert key. |
| `activeEnergyKcal` | number | move ring. |
| `exerciseMinutes` | integer | exercise ring. |
| `standHours` | integer | stand ring. |
| `steps` | integer \| null | high NEAT signal (§1). |

## DailyCheckin

The few daily **objective** taps. Upsert by `date` (`checkins` table). Feeds the **safety gate (§6.2)** —
readiness (§6.1) is objective-only and does **not** read the check-in. No subjective self-report.
**Body weight is not here** — it comes from HealthKit (`body_mass` record), like all other measurements.

```json
{
  "date": "2026-06-02",
  "giSymptoms": false,
  "kneePain": 1,
  "illness": false
}
```

| Field | Type | Notes |
|---|---|---|
| `date` | date | upsert key. |
| `giSymptoms` | boolean | a single yes/no — **any** GI flare sign (blood / >4 loose stools / urgency / abdominal pain). `true` → GI-flare safety gate + nutrition deload (§6.2 / §8.1). |
| `kneePain` | integer 0–10 | **`0` = none.** `>3` → impact gate: no running/jumping (§6.2 / §8.2). |
| `illness` | boolean | illness / fever → safety-gate rest (§6.2). |

## StrengthTest

Two numbers on test days. Server derives the ISO week (`strength_tests` table, §9/§10 KPI).

```json
{ "date": "2026-06-02", "maxPushups": 42, "maxPullups": 11 }
```

| Field | Type | Notes |
|---|---|---|
| `date` | date | server maps to the ISO week. |
| `maxPushups` | integer | trend-smoothed KPI. |
| `maxPullups` | integer | trend-smoothed KPI. |

## SyncResponse

Idempotency is observable — counts split upserted vs ignored duplicates. `/sync` does **no** readiness computation; that happens in the brief.

```json
{
  "recordsUpserted": 1,
  "recordsDuplicate": 0,
  "workoutsUpserted": 0,
  "activityDaysUpserted": 0,
  "checkinSaved": true,
  "strengthTestSaved": false,
  "serverTime": "2026-06-02T06:20:11+03:00"
}
```

| Field | Type | Notes |
|---|---|---|
| `recordsUpserted` | integer | new/updated records. |
| `recordsDuplicate` | integer | ignored by `uuid` (idempotent). |
| `workoutsUpserted` | integer | |
| `activityDaysUpserted` | integer | |
| `checkinSaved` | boolean | |
| `strengthTestSaved` | boolean | |
| `serverTime` | datetime | server clock, for drift checks. |

---

# `POST /brief/daily`

Get-or-generate today's tuned session. First request of a date runs `DAILY_ADJUSTER`; later requests serve the cache. `?refresh=true` forces regeneration. The response is **`{ data, narrative }`**.

## DailyBriefRequest

Body is near-empty (single user, token in header). `date` defaults to today in Europe/Sofia.

```json
{ "date": "2026-06-02" }
```

| Field | Type | Notes |
|---|---|---|
| `date` | date \| null | target day; default = today (Europe/Sofia). |

## Readiness

Computed by `ComputeReadinessNode` (§6.1) — **purely physiological** (sleep, HRV, RHR, yesterday's load). `penalties` is itemised for transparency.

```json
{
  "score": 60,
  "band": "amber",
  "penalties": [
    { "factor": "sleep_below_7h", "points": -10 },
    { "factor": "hrv_below_baseline", "points": -15 },
    { "factor": "yesterday_hard_day", "points": -15 }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `score` | integer 0–100 | starts at 100, subtract penalties, **clamp to [0, 100]**. |
| `band` | `ReadinessBand` | `green` ≥75 · `amber` 50–74 · `red` <50. |
| `penalties` | ReadinessPenalty[] | each `{ factor, points }`; `points` negative. |

**ReadinessPenalty** — `{ "factor": "sleep_below_7h", "points": -10 }`. `factor` keys: `sleep_below_7h`, `sleep_below_5h`, `hrv_below_baseline`, `rhr_above_baseline`, `yesterday_hard_day`. *(Subjective energy/soreness/motivation penalties were dropped with the check-in fields — readiness is now objective-only.)*

## SafetyGate

Computed by `SafetyGateRouter` (§6.2) **before** the LLM. Any reason ⇒ `triggered: true`, the LLM is skipped, and `overrideTo` is the forced card.

```json
{ "triggered": false, "reasons": [], "overrideTo": null }
```

Triggered example:

```json
{
  "triggered": true,
  "reasons": ["knee_pain_high"],
  "overrideTo": "active_recovery"
}
```

| Field | Type | Notes |
|---|---|---|
| `triggered` | boolean | any gate fired. |
| `reasons` | string[] | machine keys: `gi_flare` (from `giSymptoms`), `sleep_below_4h`, `illness`, `knee_pain_high`, `rhr_spike`, `hrv_crash`. |
| `overrideTo` | `WorkoutCard` \| null | forced card when triggered — `rest` / `active_recovery` / `mobility`. |

## MacroFocus

The day's nutrition target (§7) — **all macro numbers are code-computed**. The `dayType` here is the one
the **LLM picked** (guarded; §7.3) and echoed for display; code derives every gram from it. The dietary
prose/medical filters are a `nutrition` narrative section.

```json
{
  "dayType": "moderate",
  "caloriesKcal": 2520,
  "proteinG": 146,
  "carbsG": 245,
  "fatGLow": 65,
  "fatGHigh": 80,
  "hydrationLLow": 3.0,
  "hydrationLHigh": 3.5
}
```

| Field | Type | Notes |
|---|---|---|
| `dayType` | `DayType` | carb-cycling lever — **LLM-chosen, guarded** (defaults to the card's `day_type`; floored at `hard` for hard/long sessions). |
| `caloriesKcal` | integer | day total (code · TDEE × day type). |
| `proteinG` | integer | ~constant 1.8 g/kg (§7.2). |
| `carbsG` | integer | set by `dayType`. |
| `fatGLow` / `fatGHigh` | integer | 0.8–1.0 g/kg range. |
| `hydrationLLow` / `hydrationLHigh` | number | 3.0–3.5 L + sweat replacement. |

## IntakeSummary

What was actually **logged** (consumed) for a day, from the ingested HealthKit dietary records — so the
brief can report intake-vs-target. All code-derived from `daily_metrics`. Daily brief ships yesterday's;
the weekly brief ships the 7-day average (see `WeeklyNutrition`).

```json
{
  "date": "2026-06-01",
  "caloriesKcal": 2610,
  "proteinG": 138,
  "carbsG": 250,
  "fatG": 82,
  "fiberG": 21,
  "waterL": 2.4,
  "vsTarget": { "caloriesPct": 1.04, "proteinHit": false }
}
```

| Field | Type | Notes |
|---|---|---|
| `date` | date | the day the intake covers. |
| `caloriesKcal` / `proteinG` / `carbsG` / `fatG` / `fiberG` | number \| null | logged totals (null if nothing logged). |
| `waterL` | number \| null | logged water. |
| `vsTarget` | object | `caloriesPct` = consumed ÷ target; `proteinHit` = met the protein floor. |

## SessionBlock

One workout as **pure structured data** — the merged, code-completed shape for `session` and each `alternatives` entry. No prose; the human description is an LLM `session` narrative section. **Per derive-don't-emit, the LLM emits only the `SessionPick` subset (`card` + dose); the rest is filled from `CARD_META`.**

```json
{
  "card": "easy_run",
  "intensity": "easy",
  "zoneTarget": "z2",
  "durationMinLow": 30,
  "durationMinHigh": 40,
  "hrCapBpm": 146,
  "cadenceSpm": 170,
  "flags": ["impact"]
}
```

| Field | Type | Source | Notes |
|---|---|---|---|
| `card` | `WorkoutCard` | **LLM** | the pick from the pool (§4). |
| `durationMinLow` / `durationMinHigh` | integer | **LLM** | the dose — chosen within the card's allowed band ([`CARDS.md`](./CARDS.md)); validator checks it's in-band. |
| `intensity` | `Intensity` | code | `easy` / `quality` / `recovery` — from `CARD_META[card]`. |
| `zoneTarget` | `Zone` \| null | code | target HR zone — from `CARD_META[card]`. |
| `hrCapBpm` | integer \| null | code | e.g. the 146 easy-run cap (§3) — from `CARD_META[card]`. |
| `cadenceSpm` | integer \| null | code | run cards get the current cue (`profile.yaml cadence_current_spm`); else null. |
| `flags` | string[] | code | machine keys, e.g. `impact`, `needs_green_knee` — from `CARD_META[card]`. |

**`SessionPick`** (what the LLM actually emits) — `{ "card": "easy_run", "durationMinLow": 30, "durationMinHigh": 40 }`. Code expands it into the full `SessionBlock` above via `CARD_META`.

## DailyBriefLLMOutput

The strict `OutputType` from `TuneSessionNode`: **slim picks** (`SessionPick`s) **plus the guarded `dayType` lever** **plus** the coach narrative. Code supplies readiness, the gate, the derived `SessionBlock` fields, and the macro numbers (computed from the LLM's `dayType`). Absent (LLM skipped) when the safety gate fired.

```json
{
  "session": { "card": "easy_run", "durationMinLow": 30, "durationMinHigh": 40 },
  "alternatives": [
    { "card": "steady_cardio", "durationMinLow": 30, "durationMinHigh": 45 }
  ],
  "skipOk": true,
  "dayType": "moderate",
  "narrative": [
    { "type": "summary", "heading": "Ease off today",
      "body": "Yesterday's boxing plus short sleep put you in the amber zone — keep it aerobic and skip the top end." },
    { "type": "session", "heading": "Easy aerobic run",
      "body": "30–40 min, average HR at or below 146. Walk the hills. Finish with 6–8 strides for cadence." },
    { "type": "nutrition", "heading": "Moderate fuel",
      "body": "Spread fat across meals (gallbladder). Add lemon water for citrate; calcium with meals." }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `session` | SessionPick | the pick — `card` + dose only. |
| `alternatives` | SessionPick[] | max 2 — `card` + dose each. |
| `skipOk` | boolean | safe to skip today (judgment). |
| `dayType` | `DayType` | **the LLM's nutrition lever** — guarded (a hard/long session floors it at `hard`); defaults to the card's `day_type`. |
| `narrative` | NarrativeSection[] | coach prose for display. |

> Code then expands each `SessionPick` → full `SessionBlock` via `CARD_META`, validates the chosen `dayType` against the guardrail, and computes `MacroFocus` from it.

## DailyBrief

The assembled response in two parts: **`data`** (pure structured — build the UI) and **`narrative`** (LLM coach prose — render for the user).

```json
{
  "data": {
    "date": "2026-06-02",
    "readiness": {
      "score": 60, "band": "amber",
      "penalties": [
        { "factor": "sleep_below_7h", "points": -10 },
        { "factor": "hrv_below_baseline", "points": -15 },
        { "factor": "yesterday_hard_day", "points": -15 }
      ]
    },
    "safetyGate": { "triggered": false, "reasons": [], "overrideTo": null },
    "session": {
      "card": "easy_run", "intensity": "easy", "zoneTarget": "z2",
      "durationMinLow": 30, "durationMinHigh": 40,
      "hrCapBpm": 146, "cadenceSpm": 170, "flags": ["impact"]
    },
    "alternatives": [],
    "skipOk": true,
    "macroFocus": {
      "dayType": "moderate", "caloriesKcal": 2520, "proteinG": 146, "carbsG": 245,
      "fatGLow": 65, "fatGHigh": 80, "hydrationLLow": 3.0, "hydrationLHigh": 3.5
    },
    "intakeYesterday": {
      "date": "2026-06-01", "caloriesKcal": 2610, "proteinG": 138, "carbsG": 250,
      "fatG": 82, "fiberG": 21, "waterL": 2.4,
      "vsTarget": { "caloriesPct": 1.04, "proteinHit": false }
    },
    "generatedAt": "2026-06-02T06:20:13+03:00",
    "cached": false,
    "constitutionVersion": "2026-05-01"
  },
  "narrative": [
    { "type": "summary", "heading": "Ease off today",
      "body": "Amber readiness after boxing and short sleep — keep it aerobic." },
    { "type": "session", "heading": "Easy aerobic run",
      "body": "30–40 min, HR ≤146, walk the hills, 6–8 strides to finish." }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `data` | object | pure structured payload (fields below). |
| `data.date` | date | the period key. |
| `data.readiness` | Readiness | code. |
| `data.safetyGate` | SafetyGate | code. |
| `data.session` | SessionBlock | LLM choice, or the gate override. |
| `data.alternatives` | SessionBlock[] | LLM (empty when gated). |
| `data.skipOk` | boolean | |
| `data.macroFocus` | MacroFocus | code numbers; `dayType` derived from the session. |
| `data.intakeYesterday` | IntakeSummary \| null | yesterday's logged intake vs target (null if nothing logged). |
| `data.generatedAt` | datetime | |
| `data.cached` | boolean | served from cache vs freshly generated. |
| `data.constitutionVersion` | string \| null | constitution snapshot used. |
| `narrative` | NarrativeSection[] | LLM coach prose, in render order; code-written when gated. |

---

# `POST /brief/weekly`

Get-or-generate this week's tiered plan. First request of an ISO week runs `WEEKLY_PLANNER` (and the §10 constants recompute when stale). `?refresh=true` forces regeneration. Same **`{ data, narrative }`** shape as the daily brief.

## WeeklyBriefRequest

```json
{ "isoWeek": "2026-W23" }
```

| Field | Type | Notes |
|---|---|---|
| `isoWeek` | string \| null | `YYYY-Www`; default = current ISO week (Europe/Sofia). |

## WeeklyBudgets

The skeleton, computed by `ComputeBudgetsNode` (§5.1) — the hard limits the LLM plans within.

```json
{
  "hardDays": 2,
  "strengthSessions": 2,
  "longRunKm": 11.0,
  "deload": false
}
```

| Field | Type | Notes |
|---|---|---|
| `hardDays` | integer | 2, or 3 only when sleep ≥6.5h + HRV ≥baseline + no GI (§5.1). |
| `strengthSessions` | integer | protected at 2 (the muscle goal). |
| `longRunKm` | number \| null | capped ≤10%/wk ramp (§9). |
| `deload` | boolean | every 4th week, or auto-triggered (§8). |

> *(`easyRatioTarget` was removed — it duplicated `WeeklyTargets.easyRunRatio`. The ~0.8 polarization target is the LLM's planned ratio in `WeeklyTargets`, derived from the fixed §3 80/20 rule.)*

## PlannedSession

One session in the week as the **merged, code-completed** shape. The descriptive prescription is a `session` narrative section. `suggestedDay` is a hint the daily loop may shuffle (§5.2). **The LLM emits only the `PlannedPick` subset; the card-determined fields are filled from `CARD_META`.**

```json
{
  "card": "vo2",
  "tier": "core",
  "intensity": "quality",
  "isHardDay": true,
  "suggestedDay": "fri",
  "zoneTarget": "z5",
  "durationMinLow": 30,
  "durationMinHigh": 40,
  "flags": ["quality_day", "needs_green_knee"]
}
```

| Field | Type | Source | Notes |
|---|---|---|---|
| `card` | `WorkoutCard` | **LLM** | pool card. |
| `suggestedDay` | `Weekday` \| null | **LLM** | sequencing hint; not a fixed calendar. |
| `durationMinLow` / `durationMinHigh` | integer \| null | **LLM** | the dose — within the card's band. |
| `tier` | `Tier` | code | `core` / `extra` — implied by which array (`core[]` vs `extras[]`) the pick sits in. |
| `intensity` | `Intensity` | code | from `CARD_META[card]`. |
| `isHardDay` | boolean | code | from `CARD_META[card]` — so the hard-day count is always trustworthy. |
| `zoneTarget` | `Zone` \| null | code | from `CARD_META[card]`. |
| `flags` | string[] | code | machine keys, e.g. `prehab:foot`, `quality_day` — from `CARD_META[card]`. |

**`PlannedPick`** (what the LLM emits) — `{ "card": "vo2", "suggestedDay": "fri", "durationMinLow": 30, "durationMinHigh": 40 }`.

## WeeklyTargets

Week-level numeric targets the daily loop measures against — **numbers only, all code-derived** by
`ComputeTargetsNode` from the LLM's picks (they're sums/ratios = arithmetic, so the LLM never emits them).

```json
{
  "totalRunKm": 28.0,
  "easyRunRatio": 0.8,
  "strengthSessions": 2,
  "hardDays": 2,
  "cadenceSpm": 160
}
```

| Field | Type | Notes |
|---|---|---|
| `totalRunKm` | number \| null | sum of run-card doses (× pace model). |
| `easyRunRatio` | number | easy-run share over total run time (target ~0.8 polarization). |
| `strengthSessions` | integer | count of strength cards. |
| `hardDays` | integer | count of `isHardDay` cards. |
| `cadenceSpm` | integer | this month's cue from `profile.yaml cadence_current_spm` (ramps +5/2–3wk). |

## WeeklyNutrition

Nutrition as a **first-class half of the weekly brief** (§7). **All code-derived** — the constant
targets from `profile.yaml` + live weight, the `dayTypePattern` from the planned picks (each session's
intensity → its day type), and `lastWeek` from the ingested dietary intake. The prose lives in a
`nutrition` narrative section.

```json
{
  "proteinG": 146,
  "fatGLow": 65, "fatGHigh": 80,
  "hydrationLLow": 3.0, "hydrationLHigh": 3.5,
  "avgCaloriesKcal": 2520,
  "dayTypePattern": [
    { "suggestedDay": "mon", "dayType": "moderate", "caloriesKcal": 2520, "carbsG": 245 },
    { "suggestedDay": "tue", "dayType": "hard",     "caloriesKcal": 2800, "carbsG": 365 },
    { "suggestedDay": "fri", "dayType": "hard",     "caloriesKcal": 2800, "carbsG": 365 }
  ],
  "lastWeek": {
    "avgCaloriesKcal": 2610, "avgProteinG": 138,
    "proteinHitDays": 4, "daysOverTarget": 3, "daysUnderTarget": 1
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `proteinG` | integer | constant daily target (1.8 g/kg × live weight). |
| `fatGLow` / `fatGHigh` | integer | 0.8–1.0 g/kg range. |
| `hydrationLLow` / `hydrationLHigh` | number | baseline + sweat replacement. |
| `avgCaloriesKcal` | integer | week-average target (nets to the §7.1 deficit). |
| `dayTypePattern` | array | one entry per planned session — `{ suggestedDay, dayType, caloriesKcal, carbsG }`, derived from the picks. |
| `lastWeek` | object \| null | 7-day intake adherence from HealthKit: avg calories/protein, protein-hit days, days over/under target. |

## WeeklyPlanLLMOutput

The strict `OutputType` from `GeneratePlanNode` — **slim picks** (`PlannedPick`s in `core`/`extras`) plus the plan narrative, within the budgets. `targets`, the carb day-type pattern, and every card-derived field are computed downstream — not emitted.

```json
{
  "core": [
    { "card": "boxing",        "suggestedDay": "tue", "durationMinLow": 60, "durationMinHigh": 90 },
    { "card": "vo2",           "suggestedDay": "fri", "durationMinLow": 30, "durationMinHigh": 40 },
    { "card": "strength_pull", "suggestedDay": "mon", "durationMinLow": 30, "durationMinHigh": 45 }
  ],
  "extras": [
    { "card": "easy_run",      "suggestedDay": "wed", "durationMinLow": 30, "durationMinHigh": 40 }
  ],
  "narrative": [
    { "type": "plan", "heading": "Two hard days around boxing",
      "body": "Boxing (Tue) and VO₂ (Fri) are the two quality days, spaced apart; pull strength stays core for the muscle goal." },
    { "type": "session", "heading": "VO₂ intervals",
      "body": "5 × 3 min at Z5 with equal jog recovery — only if the knee is green." },
    { "type": "nutrition", "heading": "Fuel the hard days",
      "body": "Carb-load Tue & Fri around boxing/VO₂; pull rest-day carbs back to drive the deficit. Protein constant ~146 g." }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `core` | PlannedPick[] | 2–3 high-priority picks (`card` + day + dose). |
| `extras` | PlannedPick[] | 1–2 optional picks. |
| `narrative` | NarrativeSection[] | coach prose for display (incl. a `nutrition` section — §7). |

> Code then expands each pick → `PlannedSession`, derives `WeeklyTargets` and the `WeeklyNutrition` day-type pattern, and merges the code-computed `WeeklyBudgets`.

## WeeklyPlan

The assembled response: **`data`** (deterministic budgets/recompute + the LLM's structured plan) and **`narrative`** (LLM coach prose).

```json
{
  "data": {
    "isoWeek": "2026-W23",
    "weekStart": "2026-06-01",
    "budgets": { "hardDays": 2, "strengthSessions": 2, "longRunKm": 11.0, "deload": false },
    "core": [],
    "extras": [],
    "targets": { "totalRunKm": 28.0, "easyRunRatio": 0.8, "strengthSessions": 2, "hardDays": 2, "cadenceSpm": 160 },
    "nutrition": {
      "proteinG": 146, "fatGLow": 65, "fatGHigh": 80, "hydrationLLow": 3.0, "hydrationLHigh": 3.5,
      "avgCaloriesKcal": 2520, "dayTypePattern": [], "lastWeek": null
    },
    "constantsRecomputed": false,
    "generatedAt": "2026-06-01T06:20:13+03:00",
    "cached": false
  },
  "narrative": [
    { "type": "plan", "heading": "Two hard days around boxing",
      "body": "Boxing + VO₂ are the hard days; pull protected as core." },
    { "type": "nutrition", "heading": "Carb-cycle around the hard days",
      "body": "Maintenance carbs Tue/Fri, pulled back on rest days; protein constant. You were ~4% over target last week." }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `data` | object | pure structured payload (fields below). |
| `data.isoWeek` | string | the period key. |
| `data.weekStart` | date | Monday of the ISO week (Europe/Sofia). |
| `data.budgets` | WeeklyBudgets | code. |
| `data.core` / `data.extras` | PlannedSession[] | LLM picks, expanded by code via `CARD_META`. |
| `data.targets` | WeeklyTargets | code (derived from the picks). |
| `data.nutrition` | WeeklyNutrition | code (targets + day-type pattern + last-week adherence). |
| `data.constantsRecomputed` | boolean | §10 recompute ran this week. |
| `data.generatedAt` | datetime | |
| `data.cached` | boolean | |
| `narrative` | NarrativeSection[] | LLM coach prose, in render order. |

---

# Errors

One envelope for all non-2xx responses.

## Error

```json
{
  "error": {
    "code": "brief_generation_failed",
    "message": "The daily brief could not be generated.",
    "detail": "Upstream LLM timeout after 30s."
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `error.code` | string | stable machine code — `validation_error`, `not_found`, `brief_generation_failed`, `upstream_timeout`, `unauthorized`. |
| `error.message` | string | human-readable summary. |
| `error.detail` | string \| null | optional extra context. |

---

*The **`.md` is the source of truth**; `models.html` is generated from it (regenerate on change).
Inline comments live in `models.html` (localStorage) and export to `models-comments.json` / `models-comments.md` in this folder — drop the export here and I'll read and act on it.*
