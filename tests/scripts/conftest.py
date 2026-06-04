"""Shared fixtures for the offline `scripts/build_db.py` tests.

`build_db.py` is a standalone offline ETL script (it deliberately lives outside
`app/` and imports nothing from the runtime), so we load it by path via importlib
rather than as an installed package.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
BUILD_DB_PATH = SCRIPTS_DIR / "build_db.py"
FIXTURE_XML = REPO_ROOT / "tests" / "fixtures" / "health_export_small.xml"

# Put scripts/ on the import path so offline scripts that import a sibling module
# (e.g. derive_constants importing compute_zones) resolve under pytest, the same
# way Python adds the script dir to sys.path when run as `python scripts/...`.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


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


@pytest.fixture(scope="session")
def derive_constants() -> ModuleType:
    """The `scripts/derive_constants.py` module (scripts/ is on sys.path)."""
    return importlib.import_module("derive_constants")


@pytest.fixture(scope="session")
def compute_zones_mod() -> ModuleType:
    """The `scripts/compute_zones.py` module (scripts/ is on sys.path)."""
    return importlib.import_module("compute_zones")
