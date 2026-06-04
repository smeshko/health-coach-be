"""Shared fixtures for the offline `scripts/build_db.py` tests.

`build_db.py` is a standalone offline ETL script (it deliberately lives outside
`app/` and imports nothing from the runtime), so we load it by path via importlib
rather than as an installed package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DB_PATH = REPO_ROOT / "scripts" / "build_db.py"
FIXTURE_XML = REPO_ROOT / "tests" / "fixtures" / "health_export_small.xml"


@pytest.fixture(scope="session")
def build_db() -> ModuleType:
    """The `scripts/build_db.py` module, loaded from source by path."""
    spec = importlib.util.spec_from_file_location("build_db", BUILD_DB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def fixture_xml() -> Path:
    """Path to the tiny synthetic export.xml (never the real corpus)."""
    return FIXTURE_XML


@pytest.fixture(scope="session")
def build_db_source() -> str:
    """Raw source text of `scripts/build_db.py` for structural assertions."""
    return BUILD_DB_PATH.read_text()
