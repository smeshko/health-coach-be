"""`activity_summary` — daily Apple Watch rings (ingest).

One row per Europe/Sofia day, **upserted by date** — so `date` (TEXT) is the PK, no
surrogate `id`, matching the date-PK pattern `daily_metrics`/`checkins` use in
E2·P3. In SQLite a non-`WITHOUT ROWID` TEXT PRIMARY KEY is **NULL-tolerant**, so
`date` is declared `nullable=False` explicitly — otherwise multiple `date=NULL` rows
would slip in and silently break the upsert (DB.md §1; round-1 #1). The stand-hours
columns are INTEGER; the energy/exercise/move columns (+goals) are REAL.
"""

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ActivitySummary(Base):
    __tablename__ = "activity_summary"

    date: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    active_energy_burned: Mapped[float | None] = mapped_column(Float)
    active_energy_burned_goal: Mapped[float | None] = mapped_column(Float)
    apple_exercise_time: Mapped[float | None] = mapped_column(Float)
    apple_exercise_time_goal: Mapped[float | None] = mapped_column(Float)
    apple_stand_hours: Mapped[int | None] = mapped_column(Integer)
    apple_stand_hours_goal: Mapped[int | None] = mapped_column(Integer)
    apple_move_time: Mapped[float | None] = mapped_column(Float)
    apple_move_time_goal: Mapped[float | None] = mapped_column(Float)
