from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.common import APIModel


class AssessmentRequest(APIModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    goal: str
    gender: str
    weight_kg: float = Field(gt=0)
    age: int = Field(ge=13, le=100)
    has_experience: bool
    fitness_level: int = Field(ge=1, le=10)
    limitations: list[str] = Field(default_factory=list)
    diet: str
    days_per_week: int = Field(ge=1, le=7)
    exercise_preferences: list[str] = Field(default_factory=list)
    takes_supplements: bool = False
    supplements: list[str] = Field(default_factory=list)
    calorie_goal: int = Field(ge=800, le=6000)
    sleep_quality: str
    body_scan_captured: bool = False
    voice_captured: bool = False
    concerns: str = ""


class TraineeUpdateOut(APIModel):
    goal: str
    weight_kg: float
    daily_calorie_target: int
    protein_g: int
    carbs_g: int
    fat_g: int


class SafetyOut(APIModel):
    avoid: list[str]
    modifications: list[str]
    medical_note: str | None = None


class GeneratedExerciseOut(APIModel):
    exercise_name: str
    muscle_group: str
    equipment: str
    difficulty: str
    cues: list[str]
    sets: int
    reps: int
    rest_seconds: int
    recommended_weight_kg: float | None = None
    tempo: str | None = None
    rpe: float | None = None
    notes: str | None = None
    prescribed_sets: list[dict] = Field(default_factory=list)


class GeneratedDayOut(APIModel):
    weekday: str
    start_time: str | None = None
    title: str
    focus: str
    duration_minutes: int
    location: str | None = None
    warmup: str | None = None
    cooldown: str | None = None
    coach_notes: str | None = None
    exercises: list[GeneratedExerciseOut] = Field(default_factory=list)


class GeneratedPlanOut(APIModel):
    title: str
    focus: str
    duration_minutes: int
    level: str
    days_per_week: int
    notes: str | None = None
    days: list[GeneratedDayOut]


class AssessmentProgramOut(APIModel):
    trainee_update: TraineeUpdateOut
    safety: SafetyOut
    coach_summary: str
    nutrition_notes: str
    plan: GeneratedPlanOut
