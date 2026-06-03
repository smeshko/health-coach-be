"""`checkins` — the daily check-in (DB.md §3).

Objective-only: readiness is physiological, so the check-in carries no subjective
self-report and the GI check is a single boolean. **No body-weight field** — weight
comes from HealthKit `body_mass` → `daily_metrics.body_weight`. `date` is the TEXT
PK (upsertable by date), declared `nullable=False` (SQLite TEXT PKs are NULL-tolerant).
`knee_pain` is 0–10 (0 = none), not a boolean. Range invariants are enforced at the
write layer (E5), not as DB CHECK constraints. Schema only.
"""

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Checkins(Base):
    __tablename__ = "checkins"

    date: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    gi_symptoms: Mapped[int | None] = mapped_column(Integer)
    illness: Mapped[int | None] = mapped_column(Integer)
    knee_pain: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)
