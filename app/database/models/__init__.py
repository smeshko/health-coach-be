"""Ingest + derived ORM models.

Importing this package registers every model on the shared `Base.metadata`, so
`alembic/env.py` (which imports it) sees them as the autogenerate target. Re-export
each model here as it lands (records: TASK-001; workouts/workout_statistics:
TASK-002; activity_summary: TASK-003).
"""

from app.database.models.activity_summary import ActivitySummary
from app.database.models.daily_metrics import DailyMetrics
from app.database.models.records import Records
from app.database.models.workout_statistics import WorkoutStatistics
from app.database.models.workouts import Workouts

__all__ = [
    "ActivitySummary",
    "DailyMetrics",
    "Records",
    "WorkoutStatistics",
    "Workouts",
]
