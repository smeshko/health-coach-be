"""ORM models for the nine `app.db` tables.

Importing this package registers every model on the shared `Base.metadata`, so
`alembic/env.py` (which imports it) sees them as the autogenerate target. Four
ingest tables (E2·P2: records, workouts, workout_statistics, activity_summary) plus
five derived/coaching-state tables (E2·P3: daily_metrics, checkins, strength_tests,
plans, suggestions) — re-export each below.
"""

from app.database.models.activity_summary import ActivitySummary
from app.database.models.checkins import Checkins
from app.database.models.daily_metrics import DailyMetrics
from app.database.models.plans import Plans
from app.database.models.records import Records
from app.database.models.strength_tests import StrengthTests
from app.database.models.suggestions import Suggestions
from app.database.models.workout_statistics import WorkoutStatistics
from app.database.models.workouts import Workouts

__all__ = [
    "ActivitySummary",
    "Checkins",
    "DailyMetrics",
    "Plans",
    "Records",
    "StrengthTests",
    "Suggestions",
    "WorkoutStatistics",
    "Workouts",
]
