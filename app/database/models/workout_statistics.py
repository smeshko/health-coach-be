"""`workout_statistics` — per-workout aggregates (ingest).

Each row is a HR/speed/power/cadence aggregate for one workout, linked by a FK
`workout_id → workouts(id)`. The FK is enforced at runtime because E2·P1's connect
listener issues `PRAGMA foreign_keys=ON`; the ingest migration drops this child
table before `workouts` so the round-trip never dangles (DB.md §1; epic R5).
"""

from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkoutStatistics(Base):
    __tablename__ = "workout_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workouts.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[str | None] = mapped_column(Text)
    end_date: Mapped[str | None] = mapped_column(Text)
    sum: Mapped[float | None] = mapped_column(Float)
    average: Mapped[float | None] = mapped_column(Float)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index(None, "workout_id", "type"),)
