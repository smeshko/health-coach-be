# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e4-p1-build-db-etl`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (a named command or
test), the offline `scripts/build_db.py` produces an idempotent raw `baseline.db` with the correct four-table
shape, and nothing leaks into the runtime (`app/`) or pulls in the dropped stack.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/scripts` passes (parser + write + idempotency + streaming tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **Idempotent rebuild** — `uv run pytest tests/scripts/test_build_db_idempotent.py` proves running
      `build(...)` twice into the same `--db` leaves per-table counts stable, the total row count unchanged
      (no duplication), and the second run's four-table contents equal the first's. (epic R1, §4; DB.md §0)
- [ ] **Non-zero counts across the four tables** — `uv run pytest tests/scripts/test_build_db.py -k "count
      or counts"` proves each of `records`, `workouts`, `workout_statistics`, `activity_summary` has the
      exact expected (>0) row count for the fixture. (epic §4; §3 E4·P1)
- [ ] **Raw column shape (no runtime deltas)** — `uv run pytest tests/scripts/test_build_db.py -k "shape or
      table_info or columns"` proves `PRAGMA table_info` shows the raw column sets: `records` has **no
      `id`/PK, no `uuid`, no `origin`**; `workouts` has **no `uuid`/`origin`/`effort_score`/
      `physical_effort`** (a local autoincrement `id` allowed solely as FK target); `workout_statistics`
      has `workout_id`/`type`/dates/`sum`/`average`/`minimum`/`maximum`/`unit`; `activity_summary` keeps
      **`date_components`** (not `date`) + rings/goals with `apple_stand_hours`(+goal) INTEGER. (DB.md §0,
      §1; ARCHITECTURE §3)
- [ ] **TEXT timestamp fidelity** — `uv run pytest tests/scripts/test_build_db.py -k "timestamp or offset or
      raw"` proves a stored `start_date` is byte-equal to the fixture's raw Apple string (offset preserved,
      no UTC normalization). (DB.md §0)
- [ ] **Category vs. quantity `value`** — `uv run pytest tests/scripts/test_build_db.py -k "category or
      value_text or sleep"` proves a HKCategoryType sleep-analysis record stores its enum in `value_text`
      with `value` NULL, and a quantity record stores a numeric `value`. (DB.md §1)
- [ ] **`workout_statistics` keyed to its parent workout** — `uv run pytest tests/scripts/test_build_db.py
      -k "workout_id or fk or parent"` proves a stat row's `workout_id` equals the inserted workout's `id`.
      (DB.md §1)
- [ ] **Summary report = per-table counts** — `uv run pytest tests/scripts/test_build_db.py -k "summary or
      summarize or report"` proves `summarize(conn)` returns a mapping over exactly the four tables whose
      values equal each table's real `COUNT(*)`, and that `main()` prints it. (epic §3 E4·P1; §4)
- [ ] **Memory-bounded streaming (by construction)** — `uv run pytest tests/scripts/test_build_db_streaming.py`
      proves the parser uses `ET.iterparse` + `elem.clear()` and the `scripts/build_db.py` source contains
      **no** `ET.parse`, `ET.fromstring`, or whole-file `.read()`. (epic R1; ARCHITECTURE §6; DB.md §0)
- [ ] **Offline / never opened at runtime** — `! grep -REn "baseline\.db" app` (no `app/` module references
      the corpus) **and** `uv run pytest tests/scripts/test_build_db_streaming.py -k "import or app or
      offline"` (or an equivalent assertion) proves `scripts/build_db.py` imports nothing from `app`. (DB.md
      §0, §3; ARCHITECTURE §3, §6)
- [ ] **No dropped-stack leakage** — `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" scripts`
      returns nothing (the script is stdlib `sqlite3` + `xml.etree.ElementTree` only). (ARCHITECTURE §1)
- [ ] **Tests never read the real corpus** — `! grep -REn "export\.xml" tests` finds no reference to the
      real `../db/export.xml` (tests use the small fixture via `--xml`/`--db`). (RESEARCH Constraints)
- [ ] **Lint + suite** — `uv run ruff check .` and `uv run pytest tests/scripts` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
