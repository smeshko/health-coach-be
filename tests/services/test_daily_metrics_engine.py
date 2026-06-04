"""E6·P1 `daily_metrics` recompute engine tests.

TASK-001 covers the engine *shape*: the idempotent `ON CONFLICT(date) DO UPDATE`
upsert, the non-clobber of the five later-phase columns, the empty-set no-IO guard,
and the multi-date entry point. Per-metric correctness is TASK-002/003.

`recompute_day` is exercised directly against the migrated temp-`app.db` `session`
fixture (tests/services/conftest.py). `DailyMetricsEngine.__call__` opens its **own**
`SessionLocal()`, so its tests point the lazy runtime engine at a temp `app.db` via
the `engine_db` fixture (APP_DB_PATH + cache clears, like tests/api/routes/test_sync).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.profile import load_profile
from app.core.settings import get_settings
from app.database.engine import SessionLocal, get_engine
from app.services import daily_metrics_engine as engine_mod
from app.services.daily_metrics_engine import (
    PRESERVED_COLUMNS,
    DailyMetricsEngine,
    recompute_day,
)

PROFILE = load_profile()


def _row(session: Session, day: str) -> dict:
    """The `daily_metrics` row for `day` as a plain column→value dict."""
    mapping = (
        session.execute(text("SELECT * FROM daily_metrics WHERE date = :d"), {"d": day})
        .mappings()
        .one()
    )
    return dict(mapping)


def _count(session: Session, table: str = "daily_metrics") -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


# ---------------------------------------------------------------------------
# recompute_day — idempotent upsert + non-clobber (uses the conftest `session`).
# ---------------------------------------------------------------------------
def test_recompute_day_writes_single_row_with_computed_at(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    assert _count(session) == 1
    row = _row(session, "2026-06-01")
    assert row["date"] == "2026-06-01"
    assert row["computed_at"] is not None


def test_recompute_day_computed_at_is_timezone_aware(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    computed_at = _row(session, "2026-06-01")["computed_at"]
    assert datetime.fromisoformat(computed_at).tzinfo is not None  # now_sofia(), not naive


def test_recompute_day_is_idempotent(session: Session) -> None:
    day = date(2026, 6, 1)
    recompute_day(session, day, profile=PROFILE)
    session.commit()
    first = _row(session, "2026-06-01")

    recompute_day(session, day, profile=PROFILE)
    session.commit()
    second = _row(session, "2026-06-01")

    assert _count(session) == 1  # still one row
    computed = [c for c in first if c != "computed_at"]
    assert {c: first[c] for c in computed} == {c: second[c] for c in computed}  # identical
    assert second["computed_at"] >= first["computed_at"]  # re-written / fresh


def test_recompute_day_fresh_insert_leaves_later_phase_columns_null(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-01")
    for col in PRESERVED_COLUMNS:
        assert row[col] is None, f"{col} should be null on a fresh P1 insert"


def test_recompute_day_does_not_clobber_later_phase_columns(session: Session) -> None:
    day = date(2026, 6, 1)
    recompute_day(session, day, profile=PROFILE)
    session.commit()
    # E6·P2 / E11 fill these later — a P1 re-run must not wipe them.
    session.execute(
        text(
            "UPDATE daily_metrics SET hrv_30d_mean = 42.0, hrv_30d_sd = 5.5, "
            "rhr_30d_mean = 52.0, readiness_score = 80, band = 'GREEN' WHERE date = :d"
        ),
        {"d": "2026-06-01"},
    )
    session.commit()

    recompute_day(session, day, profile=PROFILE)
    session.commit()

    row = _row(session, "2026-06-01")
    assert row["hrv_30d_mean"] == 42.0
    assert row["hrv_30d_sd"] == 5.5
    assert row["rhr_30d_mean"] == 52.0
    assert row["readiness_score"] == 80
    assert row["band"] == "GREEN"


# ---------------------------------------------------------------------------
# DailyMetricsEngine.__call__ — entry point over the lazy runtime engine.
# ---------------------------------------------------------------------------
@pytest.fixture
def engine_db(tmp_path, monkeypatch) -> Iterator[str]:
    """Point the lazy runtime engine (`SessionLocal`/`get_engine`) at a migrated temp app.db."""
    db_path = tmp_path / "app.db"
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")
    monkeypatch.setenv("API_TOKEN", "test-api-token-0123456789")
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield str(db_path)
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_engine_writes_a_row_for_each_date(engine_db: str) -> None:
    DailyMetricsEngine()({date(2026, 6, 1), date(2026, 6, 2)})
    with sqlite3.connect(engine_db) as raw:
        dates = {r[0] for r in raw.execute("SELECT date FROM daily_metrics").fetchall()}
    assert dates == {"2026-06-01", "2026-06-02"}


def test_engine_empty_set_does_no_db_or_profile_io(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("empty affected set must not open a session or load the profile")

    monkeypatch.setattr(engine_mod, "SessionLocal", boom)
    monkeypatch.setattr(engine_mod, "load_profile", boom)
    assert DailyMetricsEngine()(set()) is None  # returns before any DB/profile access


def test_engine_raising_mid_recompute_does_not_commit(engine_db: str, monkeypatch) -> None:
    # An engine error must leave no half-written daily_metrics (the session is not
    # committed) — the route surfaces the 5xx, the day re-derives next sync.
    def boom_day(*args, **kwargs):
        raise RuntimeError("recompute_day boom")

    monkeypatch.setattr(engine_mod, "recompute_day", boom_day)
    with pytest.raises(RuntimeError):
        DailyMetricsEngine()({date(2026, 6, 1)})
    # A fresh session sees no committed row.
    sess = SessionLocal()
    try:
        assert _count(sess) == 0
    finally:
        sess.close()


def test_engine_module_has_no_http_import() -> None:
    # Pure service: the engine must not reach into FastAPI/HTTP. Scan the actual
    # import statements (the docstring legitimately names FastAPI).
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(engine_mod))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(mod.split(".")[0] in {"fastapi", "starlette"} for mod in imported)
