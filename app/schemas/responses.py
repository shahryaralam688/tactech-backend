from app.schemas.common import (
    APIModel,
    MacroEstimateOut,
    MealOut,
    PlanAssignmentOut,
    TrainerProfileOut,
    TraineeProfileOut,
    UserPublic,
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


class MeResponse(APIModel):
    user: UserPublic
    trainer: TrainerProfileOut | None = None
    trainee: TraineeProfileOut | None = None


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
