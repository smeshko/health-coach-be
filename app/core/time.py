"""Europe/Sofia period-key and ISO-8601 timestamp helpers.

Timestamps are **stored** as ISO-8601 TEXT carrying the offset HealthKit emits per
sample — `+02:00` (EET, winter), `+03:00` (EEST, summer), or a travel offset — and
they are stored byte-for-byte: no offset reformatting, no UTC normalization
(DB.md §0; ARCHITECTURE §4; epic R2). **Period keys** (`date`, `iso_week`) are
*derived* by converting through the `Europe/Sofia` tz database (DST-aware), never
by assuming a fixed offset. Used by E5/E6/E10/E11 — hence this lives in `app/core`,
not the DB layer.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

SOFIA = ZoneInfo("Europe/Sofia")


def parse_ts(value: str) -> datetime:
    """Parse an offset-aware ISO-8601 string, preserving its tzinfo/offset.

    Used for **derivation only** (period keys), not for what gets stored. Raises
    ``ValueError`` on a naive/offset-less string — HealthKit always emits an offset.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timestamp must carry a UTC offset, got naive {value!r}")
    return dt


def store_ts(value: str) -> str:
    """Validate an offset-aware ISO-8601 string and return it **unchanged**.

    The bytes written to the TEXT column are exactly what the sample emitted —
    `+0200` vs `+02:00`, fractional seconds, and travel offsets are all preserved
    (no reformatting, no UTC rewrite) (round-1 #3; DB.md §0; epic R2).
    """
    parse_ts(value)  # validates: well-formed and offset-aware, else ValueError
    return value


def _require_aware(dt: datetime) -> None:
    """Raise ``ValueError`` if ``dt`` is naive.

    A naive datetime through ``astimezone()`` would silently adopt the host local
    timezone, producing machine-dependent period keys; aware-only keeps them
    reproducible across dev/CI/containers (round-2 #3).
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (no host-tz fallback)")


def to_sofia(dt: datetime) -> datetime:
    """Convert an aware ``datetime`` to Europe/Sofia local time (DST-aware)."""
    _require_aware(dt)
    return dt.astimezone(SOFIA)


def period_date(dt: datetime) -> str:
    """Sofia-local calendar date as ``YYYY-MM-DD``."""
    return to_sofia(dt).date().isoformat()


def iso_week(dt: datetime) -> str:
    """Sofia-local ISO week as zero-padded ``YYYY-Www`` (e.g. ``2026-W23``)."""
    cal = to_sofia(dt).isocalendar()
    return f"{cal.year:04d}-W{cal.week:02d}"


def period_date_of(ts: str) -> str:
    """``period_date`` for an ISO-8601 timestamp **string** (parsed first)."""
    return period_date(parse_ts(ts))


def iso_week_of(ts: str) -> str:
    """``iso_week`` for an ISO-8601 timestamp **string** (parsed first)."""
    return iso_week(parse_ts(ts))
