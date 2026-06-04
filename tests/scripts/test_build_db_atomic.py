"""Review #1.2: a failed/malformed rebuild must not destroy an existing corpus.

build() writes to a sibling temp DB and only os.replace()s the target on full
success, so a broken export can't leave behind an empty, partial, or corrupt
baseline.db for a later seed step to silently consume.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET

import pytest


def test_failed_build_preserves_existing_baseline(build_db, fixture_xml, tmp_path) -> None:
    db_path = tmp_path / "baseline.db"

    # A good corpus exists first.
    counts = build_db.build(fixture_xml, db_path)
    assert counts["records"] == 5

    # A malformed export aborts the parse mid-stream.
    bad_xml = tmp_path / "broken.xml"
    bad_xml.write_text(
        '<?xml version="1.0"?>\n<HealthData>\n'
        '<Record type="HKQuantityTypeIdentifierStepCount" value="1"'  # truncated
    )
    with pytest.raises(ET.ParseError):
        build_db.build(bad_xml, db_path)

    # The original corpus is intact (not emptied/half-written).
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 5

    # No leftover temp artifacts in the target directory.
    assert not list(tmp_path.glob("baseline.db.*.tmp"))
