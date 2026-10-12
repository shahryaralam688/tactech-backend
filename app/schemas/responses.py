from datetime import datetime

from app.schemas.common import (
    APIModel,
    MacroEstimateOut,
    MealOut,
    PlanAssignmentOut,
    TrainerProfileOut,
    TraineeProfileOut,
    UserPublic,
    WorkoutLogOut,
    WorkoutPlanOut,
)


class TokenPair(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic
    trainer: TrainerProfileOut | None = None
    trainee: TraineeProfileOut | None = None
    assessment_completed: bool = False
    onboarding_completed: bool = False


class MeAiProBadgeOut(APIModel):
    """Lightweight self-only AI Coach Pro badge on GET /me."""

    active: bool = False
    badge_label: str | None = None
    badge_full_label: str | None = None


class MeResponse(APIModel):
    user: UserPublic
    trainer: TrainerProfileOut | None = None
    trainee: TraineeProfileOut | None = None
    assessment_completed: bool = False
    onboarding_completed: bool = False
    ai_pro: MeAiProBadgeOut | None = None


class TraineeRosterItem(APIModel):
    id: str
    user_id: str
    trainer_id: str | None
    goal: str
    height_cm: int
    weight_kg: float
    daily_calorie_target: int
    user: UserPublic
    assigned_plan: WorkoutPlanOut | None = None


class TraineeDetailResponse(TraineeRosterItem):
    pass


class AssignmentResponse(APIModel):
    assignment: PlanAssignmentOut
    plan: WorkoutPlanOut


class TrainerPublic(APIModel):
    trainer: TrainerProfileOut
    user: UserPublic


class DailyMacrosResponse(APIModel):
    trainee_id: str
    date: str
    macros: MacroEstimateOut
    meals: list[MealOut]


class TraineeAnalyticsDay(APIModel):
    date: str
    sessions: int = 0
    duration_minutes: int = 0
    volume_kg: float = 0


class TraineeExerciseStat(APIModel):
    exercise_id: str
    sets: int = 0
    reps: int = 0
    volume_kg: float = 0


class TraineeAnalyticsOut(APIModel):
    trainee_id: str
    period_days: int
    sessions_completed: int
    total_duration_minutes: int
    total_volume_kg: float
    last_workout_at: datetime | None = None
    workouts_by_day: list[TraineeAnalyticsDay]
    top_exercises: list[TraineeExerciseStat]
    recent_logs: list[WorkoutLogOut]
