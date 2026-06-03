# TASK-001: export.xml streaming parser

Depends on: None
Suggested commit: `feat(scripts): stream-parse export.xml elements (iterparse)`

## Goal

Add the memory-bounded streaming core of `scripts/build_db.py`: an `iterparse`-driven generator that walks
`export.xml` element-by-element, yields normalized `Record` / `Workout` (with its child
`WorkoutStatistics`) / `ActivitySummary` rows, and clears each processed element — never materializing the
DOM.

## Files

- `scripts/build_db.py` — new (offline ETL; stdlib `sqlite3` + `xml.etree.ElementTree` only, **no** `app/`
  import). This task lands the parse layer:
  - `iter_health_elements(xml_path)` — `for _, elem in ET.iterparse(xml_path, events=("end",)):` dispatch
    on `elem.tag`:
    - `"Record"` → yield a normalized record tuple/dict from `elem.attrib` (`type`,`unit`,`value`→both a
      coerced REAL and the raw `value_text`,`sourceName`,`sourceVersion`,`device`,`creationDate`,
      `startDate`,`endDate`).
    - `"Workout"` → yield the workout fields **plus** its child `WorkoutStatistics` rows (read via
      `elem.findall("WorkoutStatistics")` inside the workout's `end` event, before `elem.clear()`).
    - `"ActivitySummary"` → yield the rings (`dateComponents`→`date_components`, energy/exercise/move +
      goals + units, `appleStandHours`(+goal)).
    - Call `elem.clear()` after **every** processed element (bounds memory).
  - `to_float(v)` / `to_int(v)` — coerce blank/non-numeric → `None` (mirrors `../db/build_db.py`).
  - **No** `ET.parse()` / `ET.fromstring()` / whole-file `.read()` anywhere.
- `tests/fixtures/health_export_small.xml` — new tiny synthetic `export.xml` (valid HealthKit Export
  Version 14 shape): a few `<Record>`s incl. **one HKCategoryType sleep-analysis** record (enum value) and
  quantity records; ≥1 `<Workout>` with ≥1 child `<WorkoutStatistics>`; ≥2 `<ActivitySummary>` days. Use
  raw Apple-style timestamps with offsets (e.g. `"2025-04-15 07:32:11 +0300"`). Known per-element counts.
- `tests/scripts/__init__.py`, `tests/scripts/test_build_db_streaming.py` — new: structural memory-bound
  assertions + a parse smoke test over the fixture.

## Acceptance

- [ ] `iter_health_elements(fixture)` yields the expected number of record / workout / activity-summary
      items, and each workout carries its child statistics list.
- [ ] A yielded sleep-analysis record exposes its enum in `value_text` with the numeric `value` `None`; a
      quantity record exposes a numeric `value`.
- [ ] Timestamps come through **verbatim** (raw Apple string with offset), not normalized.
- [ ] `scripts/build_db.py` source uses `ET.iterparse` and `elem.clear()` and contains **no** `ET.parse`,
      `ET.fromstring`, or whole-file `.read()` (asserted by reading the source text).
- [ ] `scripts/build_db.py` imports nothing from `app`.

## Steps

### RED
- [ ] Write `tests/fixtures/health_export_small.xml` with known counts (records incl. one category record,
      a workout + a child statistic, ≥2 activity summaries).
- [ ] `tests/scripts/test_build_db_streaming.py`: import `iter_health_elements`, run it over the fixture,
      assert element counts / the category-vs-quantity `value`/`value_text` split / verbatim timestamps;
      assert the source text uses `iterparse`+`clear` and has no `ET.parse`/`fromstring`/`.read()`; assert
      no `app` import. (Tests fail — module doesn't exist yet.)

### GREEN
- [ ] Implement `iter_health_elements` + `to_float`/`to_int` in `scripts/build_db.py` (streaming dispatch +
      `elem.clear()`), smallest code to pass.

### REFACTOR
- [ ] Factor the per-tag attribute extraction into small helpers; keep the generator pure (no DB coupling)
      so TASK-002 can feed it into batched inserts. Keep all timestamp fields raw TEXT.

## Notes

`<WorkoutStatistics>` is a **child** of `<Workout>` — it must be read inside the workout's `end` event
(`elem.findall("WorkoutStatistics")`) **before** `elem.clear()`, then keyed to the parent in TASK-002.
`<Record value>` holds a numeric quantity **or** a category enum (sleep stage / stand state) that a REAL
column can't hold, so keep both a coerced float and the raw `value_text` (DB.md §1). Memory-boundedness is
proven **structurally** (iterparse + clear; no DOM load) — not by measuring RSS over the 1.5 GB corpus.
