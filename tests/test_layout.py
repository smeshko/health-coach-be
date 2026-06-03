"""Import-boundary smoke test for the package layout (E1·P1 TASK-001).

Asserts the kept-stack package skeleton imports cleanly and that the
dropped-stack distributions (Postgres/Celery/Redis/pgvector/vecs/Supabase —
ARCHITECTURE §1 stack note) never enter the locked dependency manifest.
"""

import importlib
import tomllib
from pathlib import Path

import pytest

KEPT_SUBPACKAGES = ["app.api", "app.core", "app.database", "app.services"]

# Dropped-stack distributions that must never enter the dependency tree.
FORBIDDEN_DISTS = {
    "psycopg2",
    "psycopg2-binary",
    "asyncpg",
    "celery",
    "redis",
    "pgvector",
    "vecs",
    "supabase",
}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", KEPT_SUBPACKAGES)
def test_subpackage_imports(module):
    assert importlib.import_module(module) is not None


def _locked_package_names() -> set[str]:
    lock = _PROJECT_ROOT / "uv.lock"
    data = tomllib.loads(lock.read_text())
    return {pkg["name"].lower() for pkg in data.get("package", [])}


def test_dropped_stack_absent_from_lock():
    leaked = FORBIDDEN_DISTS & _locked_package_names()
    assert not leaked, f"dropped-stack deps leaked into uv.lock: {sorted(leaked)}"
