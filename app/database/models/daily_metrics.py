"""`daily_metrics` — derived per-day materialized cache (DB.md §2).

One row per Europe/Sofia day, recomputed on sync (E6) — the single source for the
7/28-day rollups and the rolling readiness baselines. `date` is the natural TEXT PK
(no surrogate `id`), declared `nullable=False` explicitly (SQLite TEXT PKs are
NULL-tolerant). `readiness_score`/`band` are nullable: a sync-time row persists
before the daily brief (E11) fills them. Schema only — no values computed here.
"""

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DailyMetrics(Base):
    __tablename__ = "daily_metrics"

    date: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    sleep_h: Mapped[float | None] = mapped_column(Float)
    hrv_sdnn: Mapped[float | None] = mapped_column(Float)
    rhr: Mapped[float | None] = mapped_column(Float)
    hrv_30d_mean: Mapped[float | None] = mapped_column(Float)
    hrv_30d_sd: Mapped[float | None] = mapped_column(Float)
    rhr_30d_mean: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_energy: Mapped[float | None] = mapped_column(Float)
    z1_min: Mapped[float | None] = mapped_column(Float)
    z2_min: Mapped[float | None] = mapped_column(Float)
    z3_min: Mapped[float | None] = mapped_column(Float)
    z4_min: Mapped[float | None] = mapped_column(Float)
    z5_min: Mapped[float | None] = mapped_column(Float)
    kcal_in: Mapped[float | None] = mapped_column(Float)
    protein_in_g: Mapped[float | None] = mapped_column(Float)
    carbs_in_g: Mapped[float | None] = mapped_column(Float)
    fat_in_g: Mapped[float | None] = mapped_column(Float)
    fiber_in_g: Mapped[float | None] = mapped_column(Float)
    sodium_in_mg: Mapped[float | None] = mapped_column(Float)
    water_in_l: Mapped[float | None] = mapped_column(Float)
    body_weight: Mapped[float | None] = mapped_column(Float)
    hard_day: Mapped[int | None] = mapped_column(Integer)
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[str | None] = mapped_column(Text)
