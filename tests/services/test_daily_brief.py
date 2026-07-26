"""E11·P3 TASK-001: the get-or-generate service keyed by ``date`` (over a temp app.db).

The service owns lookup / refresh-delete / commit; the **workflow** (E11·P2's
``PersistSuggestionNode`` / ``SafetyRestNode``) owns the single ``suggestions`` row write.
So the stub generator here **mirrors** that node: it counts its calls, inserts one row for
the day whose ``payload`` is the ``{ data, narrative }`` brief (incl. ``intakeYesterday``),
no commit, and returns a fixed ``GeneratedDailyBrief`` — no LLM, no workflow, but the
realistic row-write path the service commits.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Suggestions
from app.services.daily_brief import (
    GeneratedDailyBrief,
    delete_suggestion,
    get_or_generate_daily,
    lookup_suggestion,
)

DATE = "2026-06-02"


def _intake_yesterday() -> dict:
    return {
        "date": "2026-06-01",
        "caloriesKcal": 2610,
        "proteinG": 138,
        "carbsG": 250,
        "fatG": 82,
        "fiberG": 21,
        "waterL": 2.4,
        "vsTarget": {"caloriesPct": 1.04, "proteinHit": False},
    }


def _data(date: str = DATE, *, marker: str = "v1", intake=True) -> dict:
    return {
        "date": date,
        "readiness": {"score": 82, "band": "green", "penalties": []},
        "safetyGate": {"triggered": False, "reasons": [], "overrideTo": None},
        "session": {
            "card": "easy_run",
            "intensity": "easy",
            "zoneTarget": "z2",
            "durationMinLow": 30,
            "durationMinHigh": 40,
            "hrCapBpm": 146,
            "cadenceSpm": 165,
            "flags": ["impact"],
        },
        "alternatives": [],
        "skipOk": False,
        "dayType": "moderate",
        "macroFocus": {
            "dayType": "moderate",
            "caloriesKcal": 2510,
            "proteinG": 140,
            "carbsG": 250,
            "fatGLow": 70,
            "fatGHigh": 90,
            "hydrationLLow": 2.5,
            "hydrationLHigh": 3.5,
        },
        "intakeYesterday": _intake_yesterday() if intake else None,
        "marker": marker,
    }


def _narrative() -> list[dict]:
    return [{"type": "summary", "heading": "Steady day", "body": "Keep it aerobic."}]


def _generated(date: str = DATE, *, marker: str = "v1", intake=True) -> GeneratedDailyBrief:
    return GeneratedDailyBrief(
        data=_data(date, marker=marker, intake=intake),
        narrative=_narrative(),
        readiness_score=82,
        band="green",
        safety_gate_tripped=0,
        gate_reason=None,
        model="claude-opus-4-8",
        constitution_version="2026.1",
        generated_at="2026-06-02T06:20:13+03:00",
    )


def _gate_tripped_generated(date: str = DATE) -> GeneratedDailyBrief:
    data = _data(date, intake=False)
    data["safetyGate"] = {"triggered": True, "reasons": ["knee_pain_high"], "overrideTo": "mobility"}
    data["session"]["card"] = "mobility"
    return GeneratedDailyBrief(
        data=data,
        narrative=[{"type": "caution", "heading": "Recovery", "body": "Rest it."}],
        readiness_score=70,
        band="amber",
        safety_gate_tripped=1,
        gate_reason="knee_pain_high",
        model=None,
        constitution_version="2026.1",
        generated_at="2026-06-02T06:20:13+03:00",
    )


class _StubGenerator:
    """Mirrors ``PersistSuggestionNode``: inserts one ``suggestions`` row (no commit), counts."""

    def __init__(self, *, marker: str = "v1", gated: bool = False) -> None:
        self.calls = 0
        self.marker = marker
        self.gated = gated

    def __call__(self, session, date: str) -> GeneratedDailyBrief:
        self.calls += 1
        gen = _gate_tripped_generated(date) if self.gated else _generated(date, marker=self.marker)
        session.execute(
            insert(Suggestions).values(
                date=date,
                payload=json.dumps({"data": gen.data, "narrative": gen.narrative}),
                readiness_score=gen.readiness_score,
                band=gen.band,
                safety_gate_tripped=gen.safety_gate_tripped,
                gate_reason=gen.gate_reason,
                inputs_snapshot=json.dumps({"readiness": gen.data["readiness"]}),
                model=gen.model,
                constitution_version=gen.constitution_version,
                created_at=gen.generated_at,
            )
        )
        return gen


def _bind(stub: _StubGenerator, session):
    """Adapt the (session, date) stub to the ``DailyBriefGenerator`` ``(date)`` seam."""

    def generate(date: str) -> GeneratedDailyBrief:
        return stub(session, date)

    return generate


def _row_count(session, date: str = DATE) -> int:
    return len(session.scalars(select(Suggestions).where(Suggestions.date == date)).all())


# --------------------------------------------------------------------------- #
# Miss → generate + commit + cached=False
# --------------------------------------------------------------------------- #
def test_miss_generates_commits_and_returns_cached_false(session) -> None:
    stub = _StubGenerator()
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=False, generate=_bind(stub, session)
    )
    assert stub.calls == 1
    assert cached is False
    assert brief.data["date"] == DATE
    assert brief.data["intakeYesterday"]["caloriesKcal"] == 2610
    session.expunge_all()
    assert _row_count(session) == 1
    row = lookup_suggestion(session, DATE)
    assert row is not None and row.payload is not None


# --------------------------------------------------------------------------- #
# Hit → stored brief, cached=True, no generate
# --------------------------------------------------------------------------- #
def test_hit_serves_stored_brief_without_generate(session) -> None:
    stub = _StubGenerator()
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(stub, session))
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=False, generate=_bind(stub, session)
    )
    assert stub.calls == 1  # not re-invoked on the hit
    assert cached is True
    assert brief.data["date"] == DATE
    assert brief.narrative == _narrative()
    # intakeYesterday round-trips identically from the stored payload.
    assert brief.data["intakeYesterday"] == _intake_yesterday()
    assert _row_count(session) == 1


# --------------------------------------------------------------------------- #
# ?refresh=true → delete then regenerate
# --------------------------------------------------------------------------- #
def test_refresh_deletes_then_regenerates(session) -> None:
    first = _StubGenerator(marker="v1")
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(first, session))
    second = _StubGenerator(marker="v2")
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=True, generate=_bind(second, session)
    )
    assert second.calls == 1
    assert cached is False
    assert brief.data["marker"] == "v2"
    assert _row_count(session) == 1  # still one row (delete + insert)
    assert json.loads(lookup_suggestion(session, DATE).payload)["data"]["marker"] == "v2"


# --------------------------------------------------------------------------- #
# ?refresh=true no-op guard — unchanged inputs serve the cache (2026-07-26)
# --------------------------------------------------------------------------- #
def test_refresh_with_matching_inputs_is_noop_cache_hit(session) -> None:
    first = _StubGenerator(marker="v1")
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(first, session))
    second = _StubGenerator(marker="v2")
    # The stub stored `inputs_snapshot={"readiness": ...}` — supply an equal fingerprint.
    brief, cached = get_or_generate_daily(
        session,
        DATE,
        refresh=True,
        generate=_bind(second, session),
        current_inputs={"readiness": _data()["readiness"]},
    )
    assert second.calls == 0  # no regeneration — the refresh was a no-op
    assert cached is True
    assert brief.data["marker"] == "v1"  # the stored brief, untouched
    assert _row_count(session) == 1


def test_refresh_with_changed_inputs_regenerates(session) -> None:
    first = _StubGenerator(marker="v1")
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(first, session))
    second = _StubGenerator(marker="v2")
    changed = {"readiness": {"score": 41, "band": "amber", "penalties": [{"rule": "sleep"}]}}
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=True, generate=_bind(second, session), current_inputs=changed
    )
    assert second.calls == 1
    assert cached is False
    assert brief.data["marker"] == "v2"
    assert _row_count(session) == 1


def test_refresh_without_current_inputs_regenerates(session) -> None:
    """`current_inputs=None` (a caller that computed nothing) is the pre-guard behaviour."""
    first = _StubGenerator(marker="v1")
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(first, session))
    second = _StubGenerator(marker="v2")
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=True, generate=_bind(second, session), current_inputs=None
    )
    assert second.calls == 1
    assert cached is False
    assert brief.data["marker"] == "v2"


def test_refresh_with_malformed_stored_snapshot_regenerates(session) -> None:
    from sqlalchemy import update

    first = _StubGenerator(marker="v1")
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(first, session))
    session.execute(
        update(Suggestions).where(Suggestions.date == DATE).values(inputs_snapshot="not json")
    )
    second = _StubGenerator(marker="v2")
    brief, cached = get_or_generate_daily(
        session,
        DATE,
        refresh=True,
        generate=_bind(second, session),
        current_inputs={"readiness": _data()["readiness"]},
    )
    assert second.calls == 1
    assert cached is False
    assert brief.data["marker"] == "v2"


# --------------------------------------------------------------------------- #
# No second writer — a duplicate generate without refresh trips UNIQUE(date)
# --------------------------------------------------------------------------- #
def test_no_second_writer_unique_date(session) -> None:
    import pathlib

    src = pathlib.Path("app/services/daily_brief.py").read_text(encoding="utf-8")
    assert "insert(Suggestions" not in src and "session.add(" not in src

    stub = _StubGenerator()
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(stub, session))
    # A direct second insert for the same date (what a buggy second writer would attempt)
    # trips UNIQUE(date) — confirming the workflow is the sole writer and the constraint
    # guarantees one brief per day. (The service's own second call HITS the cache instead.)
    with pytest.raises(IntegrityError):
        stub(session, DATE)
    session.rollback()
    assert _row_count(session) == 1


# --------------------------------------------------------------------------- #
# Gate-tripped brief round-trips as a normal (non-error) brief
# --------------------------------------------------------------------------- #
def test_gate_tripped_brief_round_trips_as_normal(session) -> None:
    stub = _StubGenerator(gated=True)
    brief, cached = get_or_generate_daily(
        session, DATE, refresh=False, generate=_bind(stub, session)
    )
    assert cached is False
    assert brief.data["safetyGate"]["triggered"] is True
    assert brief.narrative  # non-empty code narrative
    assert brief.data["alternatives"] == []
    assert brief.data["intakeYesterday"] is None
    # A subsequent hit deserialises it with the gate still tripped.
    hit, cached2 = get_or_generate_daily(
        session, DATE, refresh=False, generate=_bind(stub, session)
    )
    assert cached2 is True
    assert hit.data["safetyGate"]["triggered"] is True
    assert hit.safety_gate_tripped == 1


# --------------------------------------------------------------------------- #
# lookup/delete semantics + round-trip fidelity + intake null
# --------------------------------------------------------------------------- #
def test_lookup_and_delete_semantics(session) -> None:
    assert lookup_suggestion(session, DATE) is None
    assert delete_suggestion(session, DATE) is False
    stub = _StubGenerator()
    get_or_generate_daily(session, DATE, refresh=False, generate=_bind(stub, session))
    assert lookup_suggestion(session, DATE) is not None
    assert delete_suggestion(session, DATE) is True
    assert lookup_suggestion(session, DATE) is None


def test_round_trip_fidelity(session) -> None:
    stub = _StubGenerator()
    miss, _ = get_or_generate_daily(session, DATE, refresh=False, generate=_bind(stub, session))
    hit, cached = get_or_generate_daily(
        session, DATE, refresh=False, generate=_bind(stub, session)
    )
    assert cached is True
    assert hit.data == miss.data and hit.narrative == miss.narrative


def test_intake_yesterday_null_carried_through(session) -> None:
    stub = _StubGenerator()
    # Override the stub to return intake=None.
    def gen(date: str) -> GeneratedDailyBrief:
        stub.calls += 1
        g = _generated(date, intake=False)
        session.execute(
            insert(Suggestions).values(
                date=date,
                payload=json.dumps({"data": g.data, "narrative": g.narrative}),
                created_at=g.generated_at,
            )
        )
        return g

    brief, _ = get_or_generate_daily(session, DATE, refresh=False, generate=gen)
    assert brief.data["intakeYesterday"] is None
