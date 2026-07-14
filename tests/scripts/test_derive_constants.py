"""TASK-002/003: derive constants from baseline.db → valid profile.yaml.

A tiny synthetic baseline.db (a handful of HR/RHR/HRV/cadence `records`) is built
in tmp_path so tests are deterministic and never touch the real corpus.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.profile import load_profile

# Mirrors the E4·P1 raw `records` schema (the columns the derivation reads).
_RECORDS_DDL = """
CREATE TABLE records (
    type           TEXT NOT NULL,
    unit           TEXT,
    value          REAL,
    value_text     TEXT,
    source_name    TEXT,
    source_version TEXT,
    device         TEXT,
    creation_date  TEXT,
    start_date     TEXT NOT NULL,
    end_date       TEXT
);
"""


def _ts(day: str) -> str:
    """A raw Apple-style timestamp (offset preserved) for a given YYYY-MM-DD."""
    return f"{day} 12:00:00 +0300"


def _make_baseline_db(path: Path, dc) -> Path:
    """Build a synthetic baseline.db. `dc` is the derive_constants module (for its
    type/threshold constants). Returns the db path.

    HR is corpus-wide; RHR/HRV/cadence anchors are windowed to the trailing
    RECENT_DAYS from the latest sample. Latest sample = 2026-05-30; an
    older-than-90-days row (2026-01-01) must be excluded from the windowed anchors
    but an old HR row must still count toward max_hr.
    """
    rows: list[tuple[str, float, str]] = [
        # Heart rate — corpus-wide bounded max. 60 below floor, 235 spike above
        # ceiling (both excluded); 191 is OLD but in range → the max_hr.
        (dc.HR_TYPE, 60.0, _ts("2026-05-30")),
        (dc.HR_TYPE, 120.0, _ts("2026-05-30")),
        (dc.HR_TYPE, 150.0, _ts("2026-05-30")),
        (dc.HR_TYPE, 188.0, _ts("2026-05-30")),
        (dc.HR_TYPE, 191.0, _ts("2024-01-01")),  # old, in range, still counts
        (dc.HR_TYPE, 235.0, _ts("2026-05-30")),  # spike, excluded by ceiling
        # Resting HR — windowed median = 58; 70 (old) excluded.
        (dc.RHR_TYPE, 56.0, _ts("2026-05-20")),
        (dc.RHR_TYPE, 58.0, _ts("2026-05-25")),
        (dc.RHR_TYPE, 60.0, _ts("2026-05-30")),
        (dc.RHR_TYPE, 70.0, _ts("2026-01-01")),  # excluded (older than RECENT_DAYS)
        # HRV SDNN — windowed median = 40; 20 (old) excluded.
        (dc.HRV_TYPE, 38.0, _ts("2026-05-20")),
        (dc.HRV_TYPE, 40.0, _ts("2026-05-25")),
        (dc.HRV_TYPE, 42.0, _ts("2026-05-30")),
        (dc.HRV_TYPE, 20.0, _ts("2026-01-01")),  # excluded
        # Cadence — windowed median = 160; 140 (old) excluded.
        (dc.CADENCE_TYPE, 158.0, _ts("2026-05-20")),
        (dc.CADENCE_TYPE, 160.0, _ts("2026-05-25")),
        (dc.CADENCE_TYPE, 162.0, _ts("2026-05-30")),
        (dc.CADENCE_TYPE, 140.0, _ts("2026-01-01")),  # excluded
    ]
    con = sqlite3.connect(path)
    con.execute(_RECORDS_DDL)
    con.executemany("INSERT INTO records (type, value, start_date) VALUES (?,?,?)", rows)
    con.commit()
    con.close()
    return path


def _open_ro(dc, path: Path):
    return dc.open_readonly(path)


# --- data-derived thresholds ------------------------------------------------


def test_derive_max_hr_bounded_and_corpus_wide(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    con = _open_ro(derive_constants, db)
    try:
        # 191 (old, in range) is the max; 235 spike and 60 floor excluded; old row counts.
        assert derive_constants.derive_max_hr(con) == 191
    finally:
        con.close()


def test_windowed_anchors_match_medians(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    con = _open_ro(derive_constants, db)
    try:
        assert derive_constants.derive_rhr_baseline(con) == 58
        assert derive_constants.derive_hrv_baseline_ms(con) == 40
        assert derive_constants.derive_cadence_current_spm(con) == 160
    finally:
        con.close()


def test_easy_hr_cap_is_maffetone(derive_constants) -> None:
    cfg = derive_constants.DerivationConfig(age=34)
    assert 180 - cfg.age == 146


# --- assembled dict ---------------------------------------------------------


def test_derive_constants_dict_shape_and_caps(derive_constants, compute_zones_mod, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    con = _open_ro(derive_constants, db)
    try:
        data = derive_constants.derive_constants(con, derive_constants.DerivationConfig())
    finally:
        con.close()

    assert set(data) == {"athlete", "thresholds", "zones", "nutrition"}
    # zones is a top-level §5 section (mirrors app.core.profile.Profile), derived
    # from the data-derived max_hr/rhr.
    assert data["zones"] == compute_zones_mod.compute_zones(191, 58)
    assert data["thresholds"]["easy_hr_cap"] == 146
    assert data["thresholds"]["max_hr"] == 191
    assert data["thresholds"]["cadence_current_spm"] == 160
    # caps respected (the validator is the hard backstop in TASK-003)
    assert data["nutrition"]["deficit_pct"] <= 0.20
    assert data["nutrition"]["protein_g_per_kg"] <= 2.0


def test_cadence_falls_back_to_anchor_when_absent(derive_constants, tmp_path) -> None:
    # A corpus with no cadence rows → the config anchor is used (the real corpus
    # carries no first-class cadence sample).
    db = tmp_path / "b.db"
    con0 = sqlite3.connect(db)
    con0.execute(_RECORDS_DDL)
    con0.executemany(
        "INSERT INTO records (type, value, start_date) VALUES (?,?,?)",
        [
            (derive_constants.HR_TYPE, 188.0, _ts("2026-05-30")),
            (derive_constants.RHR_TYPE, 58.0, _ts("2026-05-30")),
            (derive_constants.HRV_TYPE, 40.0, _ts("2026-05-30")),
        ],
    )
    con0.commit()
    con0.close()
    con = _open_ro(derive_constants, db)
    try:
        assert derive_constants.derive_cadence_current_spm(con) is None
        data = derive_constants.derive_constants(con, derive_constants.DerivationConfig())
    finally:
        con.close()
    assert data["thresholds"]["cadence_current_spm"] == derive_constants.DerivationConfig().cadence_current_spm


# --- stamp / validate / write (TASK-003) ------------------------------------


def test_round_trip_loads_via_e3_validator(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    out = tmp_path / "profile.yaml"
    rc = derive_constants.main(
        ["--db", str(db), "--out", str(out), "--computed-at", "2026-06-02"]
    )
    assert rc == 0
    profile = load_profile(out)  # E3·P1 validator — raises if invalid
    assert profile.thresholds.max_hr == 191
    assert profile.zones.z5[1] == 191


def test_meta_stamped(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    out = tmp_path / "profile.yaml"
    derive_constants.main(
        ["--db", str(db), "--out", str(out), "--computed-at", "2026-06-02",
         "--constitution-version", "v1"]
    )
    profile = load_profile(out)
    assert profile.meta.derived_from == "baseline.db"
    assert profile.meta.computed_at == date.fromisoformat("2026-06-02")
    assert profile.meta.constitution_version == "v1"


def test_caps_backstop_raises_and_writes_nothing(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    out = tmp_path / "profile.yaml"
    con = _open_ro(derive_constants, db)
    try:
        with pytest.raises(ValidationError):
            profile = derive_constants.build_profile(
                con,
                derive_constants.DerivationConfig(deficit_pct=0.25),
                computed_at=date.fromisoformat("2026-06-02"),
                constitution_version="v1",
            )
            derive_constants.write_profile(profile, out)
    finally:
        con.close()
    assert not out.exists()


def test_max_hr_le_rhr_raises(derive_constants, tmp_path) -> None:
    db = tmp_path / "b.db"
    con0 = sqlite3.connect(db)
    con0.execute(_RECORDS_DDL)
    con0.executemany(
        "INSERT INTO records (type, value, start_date) VALUES (?,?,?)",
        [
            (derive_constants.HR_TYPE, 150.0, _ts("2026-05-30")),  # max_hr 150
            (derive_constants.RHR_TYPE, 160.0, _ts("2026-05-30")),  # rhr 160 >= max_hr
            (derive_constants.HRV_TYPE, 40.0, _ts("2026-05-30")),
        ],
    )
    con0.commit()
    con0.close()
    con = _open_ro(derive_constants, db)
    try:
        with pytest.raises(ValidationError):
            derive_constants.build_profile(
                con,
                derive_constants.DerivationConfig(),
                computed_at=date.fromisoformat("2026-06-02"),
                constitution_version="v1",
            )
    finally:
        con.close()


def test_determinism_byte_identical(derive_constants, tmp_path) -> None:
    db = _make_baseline_db(tmp_path / "b.db", derive_constants)
    out1 = tmp_path / "p1.yaml"
    out2 = tmp_path / "p2.yaml"
    for out in (out1, out2):
        derive_constants.main(
            ["--db", str(db), "--out", str(out), "--computed-at", "2026-06-02"]
        )
    assert out1.read_bytes() == out2.read_bytes()


def test_runtime_hr_window_matches_offline_derivation(derive_constants) -> None:
    # Phase 19.6 D4/R1: the runtime `measured_max_hr` mirrors the physiological HR window
    # app-side (it can't import this offline module). This parity assertion is the drift guard —
    # it lives HERE because the `derive_constants` fixture + `scripts/` sys.path exist only in
    # tests/scripts/conftest.py (pytest fixtures are directory-scoped).
    from app.services.recompute import _HR_CEILING, _HR_FLOOR

    assert _HR_FLOOR == derive_constants.HR_FLOOR
    assert _HR_CEILING == derive_constants.HR_CEILING
