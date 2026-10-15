"""LLM structured plan JSON — validated before persist (real exerciseIds)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import APIModel


class LlmPlanExercise(APIModel):
    exercise_id: str
    sets: int = Field(ge=1, le=20)
    reps: int = Field(ge=1, le=100)
    rest_seconds: int = Field(default=60, ge=0, le=600)
    recommended_weight_kg: float | None = None
    notes: str | None = None


class LlmPlanDay(APIModel):
    weekday: str
    title: str = ""
    focus: str = ""
    duration_minutes: int = Field(default=45, ge=10, le=180)
    warmup: str | None = None
    cooldown: str | None = None
    coach_notes: str | None = None
    exercises: list[LlmPlanExercise] = Field(default_factory=list)


class LlmWorkoutPlan(APIModel):
    """Compatible with iOS WorkoutPlan shape (camelCase via APIModel)."""

    title: str
    focus: str
    duration_minutes: int = Field(default=45, ge=10, le=180)
    level: str = "Beginner"
    days_per_week: int = Field(default=3, ge=1, le=7)
    notes: str | None = None
    days: list[LlmPlanDay] = Field(default_factory=list)
