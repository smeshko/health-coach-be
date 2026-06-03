"""Dropped-stack import guard over app/core (E1·P3 TASK-004).

Asserts no genuinely-dropped dependency appears anywhere under app/core/
(ARCHITECTURE §1 stack note). `pydantic_ai` (E9) and `langfuse` (E12) are
**kept stack** and intentionally excluded — banning them durably would block a
later epic.
"""

import re
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "app" / "core"
_BANNED = re.compile(r"celery|redis|psycopg|pgvector|supabase|vecs|boto3")


def test_no_dropped_stack_under_core():
    offenders: dict[str, list[str]] = {}
    for path in sorted(_CORE.rglob("*.py")):
        hits = sorted(set(_BANNED.findall(path.read_text())))
        if hits:
            offenders[str(path.relative_to(_CORE))] = hits
    assert not offenders, f"dropped-stack references under app/core: {offenders}"
