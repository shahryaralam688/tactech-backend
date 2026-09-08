from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.requests import RequestModel


class TemplateSetRowIn(RequestModel):
    id: str | None = None
    set_number: int = Field(ge=1)
    reps: int = Field(ge=0)
    weight_kg: float | None = None


class TemplateSetRowOut(APIModel):
    id: str
    set_number: int
    reps: int
    weight_kg: float | None = None


class ExerciseTemplateIn(RequestModel):
    id: str | None = None
    exercise_id: str
    name: str
    sets: int = Field(ge=1)
    reps: int = Field(ge=0)
    rest_seconds: int = Field(ge=0)
    weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    how_to: str | None = None
    side: str | None = None
    set_rows: list[TemplateSetRowIn] = Field(default_factory=list)


class UpdateExerciseTemplateRequest(RequestModel):
    exercise_id: str | None = None
    name: str | None = None
    sets: int | None = Field(default=None, ge=1)
    reps: int | None = Field(default=None, ge=0)
    rest_seconds: int | None = Field(default=None, ge=0)
    weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    how_to: str | None = None
    side: str | None = None
    set_rows: list[TemplateSetRowIn] | None = None


class ExerciseTemplateOut(APIModel):
    id: str
    exercise_id: str
    trainer_id: str
    name: str
    sets: int
    reps: int
    rest_seconds: int
    weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    how_to: str | None = None
    side: str | None = None
    set_rows: list[TemplateSetRowOut] = Field(default_factory=list)
    updated_at: datetime
