from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class HealthResponse(APIModel):
    status: str
    service: str


class ReadyResponse(APIModel):
    status: str
    postgres: bool
    redis: bool


class UserPublic(APIModel):
    id: str
    name: str
    email: str
    role: str
    created_at: datetime


class TrainerProfileOut(APIModel):
    id: str
    user_id: str
    invite_code: str
    specialty: str
    years_experience: int
    bio: str


class TraineeProfileOut(APIModel):
    id: str
    user_id: str
    trainer_id: str | None
    goal: str
    height_cm: int
    weight_kg: float
    daily_calorie_target: int


class ExerciseOut(APIModel):
    id: str
    name: str
    muscle_group: str
    equipment: str
    difficulty: str
    cues: list[str]
    icon: str


class WorkoutExerciseOut(APIModel):
    id: str
    exercise_id: str
    sets: int
    reps: int
    rest_seconds: int
    recommended_weight_kg: float | None = None


class WorkoutPlanOut(APIModel):
    id: str
    trainer_id: str
    title: str
    focus: str
    duration_minutes: int
    level: str
    days_per_week: int
    exercises: list[WorkoutExerciseOut] = Field(default_factory=list)


class PlanAssignmentOut(APIModel):
    id: str
    plan_id: str
    trainee_id: str
    assigned_at: datetime


class WorkoutSetLogOut(APIModel):
    id: str
    exercise_id: str
    set_number: int
    reps: int
    weight_kg: float


class WorkoutLogOut(APIModel):
    id: str
    trainee_id: str
    plan_id: str
    completed_at: datetime
    duration_minutes: int
    sets: list[WorkoutSetLogOut] = Field(default_factory=list)


class MacroEstimateOut(APIModel):
    calories: int
    protein: float
    carbs: float
    fat: float


class MealOut(APIModel):
    id: str
    trainee_id: str
    name: str
    eaten_at: datetime
    portion_grams: float
    macros: MacroEstimateOut
    source: str
    is_estimate: bool


class TrainerFeedbackOut(APIModel):
    id: str
    trainer_id: str
    trainee_id: str
    message: str
    created_at: datetime
    related_exercise_id: str | None = None


class FormReportOut(APIModel):
    id: str
    trainee_id: str
    exercise_id: str
    created_at: datetime
    score: int
    cues: list[str]
    rep_count: int


class FoodKnowledgeOut(APIModel):
    name: str
    keywords: list[str]
    per100g: MacroEstimateOut = Field(
        validation_alias=AliasChoices("per100g", "per100G"),
        serialization_alias="per100g",
    )
