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
    avatar_url: str | None = None
    avatar_asset: str | None = None


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
    gender: str | None = None
    location: str | None = None


class Form3dCameraOut(APIModel):
    pos: list[float] = Field(default_factory=list)
    target: list[float] = Field(default_factory=list)


class Form3dGuideStepOut(APIModel):
    focus: str
    title: str
    detail: str
    t: float = 0.0
    camera: Form3dCameraOut | None = None


class Form3dOut(APIModel):
    """Optional Three.js / Mixamo demo for Form Studio (character: x_bot)."""

    enabled: bool = False
    clip_id: str | None = None
    character: str | None = None
    animation_url: str | None = None
    cues: list[str] = Field(default_factory=list)
    guide: list[Form3dGuideStepOut] = Field(default_factory=list)
    attribution: str | None = None


class ExerciseOut(APIModel):
    id: str
    name: str
    # Legacy fields (unchanged for existing plan/log clients)
    muscle_group: str
    equipment: str
    difficulty: str
    cues: list[str]
    icon: str
    # Enriched catalog (iOS Form Studio + discovery)
    category: str | None = None
    muscles: list[str] = Field(default_factory=list)
    level: str | None = None
    # Spec example `equipment: string[]` — exposed as equipmentList to keep legacy string `equipment`
    equipment_list: list[str] = Field(default_factory=list)
    instructions: str | None = None
    common_mistakes: list[str] = Field(default_factory=list)
    thumbnail_url: str | None = None
    form3d: Form3dOut = Field(
        default_factory=Form3dOut,
        validation_alias=AliasChoices("form3d", "form3D"),
        serialization_alias="form3d",
    )
    updated_at: datetime | None = None


class WorkoutExerciseOut(APIModel):
    id: str
    exercise_id: str
    sets: int
    reps: int
    rest_seconds: int
    recommended_weight_kg: float | None = None


class PrescribedSetOut(APIModel):
    id: str
    set_number: int
    reps: int
    weight_kg: float | None = None
    rpe: float | None = None


class PlanDayExerciseOut(APIModel):
    id: str
    exercise_id: str
    sets: int
    reps: int
    rest_seconds: int
    recommended_weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    notes: str | None = None
    side: str | None = None
    prescribed_sets: list[PrescribedSetOut] = Field(default_factory=list)


class PlanDayOut(APIModel):
    id: str
    weekday: str
    start_time: str | None = None
    title: str
    focus: str
    duration_minutes: int
    location: str | None = None
    warmup: str | None = None
    cooldown: str | None = None
    coach_notes: str | None = None
    exercises: list[PlanDayExerciseOut] = Field(default_factory=list)


class WorkoutPlanOut(APIModel):
    id: str
    trainer_id: str | None = None
    source: str = "trainer"  # ai | trainer — iOS hides Edit/Delete unless ai
    owner_trainee_id: str | None = None
    title: str
    focus: str
    duration_minutes: int
    level: str
    days_per_week: int
    notes: str | None = None
    exercises: list[WorkoutExerciseOut] = Field(default_factory=list)
    days: list[PlanDayOut] = Field(default_factory=list)


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
