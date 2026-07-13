"""`workouts` — workout sessions (ingest).

Mirrors `baseline.db` plus `uuid`/`origin`, with two purpose-built columns that do
**not** exist in `baseline.db`: `effort_score` (RPE 1–10 from `WorkoutEffortScore`,
nullable) and `physical_effort` (METs proxy, nullable) (DB.md §1; ARCHITECTURE §3).
`uuid` is UNIQUE but nullable (seeded rows carry no UUID). Timestamps are ISO-8601
TEXT. Schema only — the write path is E5.
"""

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Workouts(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    duration: Mapped[float | None] = mapped_column(Float)
    duration_unit: Mapped[str | None] = mapped_column(Text)
    total_distance: Mapped[float | None] = mapped_column(Float)
    total_distance_unit: Mapped[str | None] = mapped_column(Text)
    total_energy_burned: Mapped[float | None] = mapped_column(Float)
    total_energy_burned_unit: Mapped[str | None] = mapped_column(Text)
    effort_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    physical_effort: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    device: Mapped[str | None] = mapped_column(Text)
    creation_date: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)

    # `start_date` is the hot filter for every date-range query (daily recompute, hard-day
    # detection, the weekly prior-long-run rollup), so index it — mirroring `records.py`
    # (Phase 19.5). Migration `0005` creates `ix_workouts_start_date`.
    __table_args__ = (
        UniqueConstraint("uuid"),
        Index(None, "start_date"),
    )
