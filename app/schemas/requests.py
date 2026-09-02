from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from app.schemas.common import APIModel, MacroEstimateOut

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class RequestModel(APIModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class SignupRequest(APIModel):
    name: str
    email: EmailStr
    password: str
    role: Literal["trainer", "trainee"]
    invite_code: str | None = None


class LoginRequest(APIModel):
    email: EmailStr
    password: str


class RefreshRequest(APIModel):
    refresh_token: str


class LogoutRequest(APIModel):
    refresh_token: str


class LinkTrainerRequest(APIModel):
    invite_code: str


class WorkoutExerciseIn(RequestModel):
    id: str | None = None
    exercise_id: str
    sets: int = Field(ge=1)
    reps: int = Field(ge=1)
    rest_seconds: int = Field(ge=0)
    recommended_weight_kg: float | None = None


class PrescribedSetIn(RequestModel):
    id: str | None = None
    set_number: int = Field(ge=1)
    reps: int = Field(ge=0)
    weight_kg: float | None = None
    rpe: float | None = None


class PlanDayExerciseIn(RequestModel):
    id: str | None = None
    exercise_id: str
    sets: int = Field(ge=1)
    reps: int = Field(ge=1)
    rest_seconds: int = Field(ge=0)
    recommended_weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    notes: str | None = None
    side: str | None = None
    prescribed_sets: list[PrescribedSetIn] = Field(default_factory=list)


class PlanDayIn(RequestModel):
    id: str | None = None
    weekday: str
    start_time: str | None = None
    title: str = ""
    focus: str = ""
    duration_minutes: int = Field(default=0, ge=0)
    location: str | None = None
    warmup: str | None = None
    cooldown: str | None = None
    coach_notes: str | None = None
    exercises: list[PlanDayExerciseIn] = Field(default_factory=list)


class CreatePlanRequest(RequestModel):
    title: str
    focus: str
    duration_minutes: int = Field(ge=1)
    level: str
    days_per_week: int = Field(ge=1, le=7)
    notes: str | None = None
    exercises: list[WorkoutExerciseIn] = Field(default_factory=list)
    days: list[PlanDayIn] = Field(default_factory=list)


class AssignPlanRequest(APIModel):
    plan_id: str
    trainee_id: str


class WorkoutSetLogIn(APIModel):
    id: str | None = None
    exercise_id: str
    set_number: int = Field(ge=1)
    reps: int = Field(ge=0)
    weight_kg: float = Field(ge=0)


class CreateWorkoutLogRequest(APIModel):
    plan_id: str
    completed_at: datetime | None = None
    duration_minutes: int = Field(ge=1)
    sets: list[WorkoutSetLogIn] = Field(default_factory=list)


class CreateMealRequest(APIModel):
    name: str
    eaten_at: datetime | None = None
    portion_grams: float = Field(gt=0)
    macros: MacroEstimateOut
    source: str = "log"
    is_estimate: bool = True


class CreateFeedbackRequest(APIModel):
    trainee_id: str
    message: str
    related_exercise_id: str | None = None


class CreateFormReportRequest(APIModel):
    exercise_id: str
    score: int = Field(ge=0, le=100)
    cues: list[str] = Field(default_factory=list)
    rep_count: int = Field(ge=0)
    created_at: datetime | None = None


class UpdateTrainerProfileRequest(APIModel):
    specialty: str | None = None
    years_experience: int | None = Field(default=None, ge=0)
    bio: str | None = None


class UpdateTraineeProfileRequest(APIModel):
    goal: str | None = None
    height_cm: int | None = Field(default=None, ge=50, le=250)
    weight_kg: float | None = Field(default=None, gt=0)
    daily_calorie_target: int | None = Field(default=None, ge=800)
