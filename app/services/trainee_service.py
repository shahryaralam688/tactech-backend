from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationAppError
from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.coaching import CoachingRepository
from app.repositories.exercise import ExerciseRepository
from app.repositories.food import FoodRepository
from app.repositories.meal import MealRepository
from app.repositories.plan import PlanRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.workout_log import WorkoutLogRepository
from app.schemas.common import (
    FormReportOut,
    MacroEstimateOut,
    MealOut,
    TrainerFeedbackOut,
    TraineeProfileOut,
    WorkoutLogOut,
    WorkoutPlanOut,
)
from app.schemas.mappers import (
    feedback_out,
    food_out,
    form_report_out,
    meal_out,
    trainer_out,
    trainee_out,
    user_public,
    workout_log_out,
    plan_out,
)
from app.schemas.requests import (
    CreateFormReportRequest,
    CreateMealRequest,
    CreateWorkoutLogRequest,
    UpdateTraineeProfileRequest,
)
from app.schemas.responses import DailyMacrosResponse, TrainerPublic


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TraineeService:
    def __init__(self, db: Session) -> None:
        self.trainees = TraineeRepository(db)
        self.trainers = TrainerRepository(db)
        self.assignments = AssignmentRepository(db)
        self.plans = PlanRepository(db)
        self.logs = WorkoutLogRepository(db)
        self.meals = MealRepository(db)
        self.coaching = CoachingRepository(db)
        self.exercises = ExerciseRepository(db)
        self.foods = FoodRepository(db)

    def update_profile(self, trainee_id: str, payload: UpdateTraineeProfileRequest) -> TraineeProfileOut:
        trainee = self.trainees.get(trainee_id)
        if trainee is None:
            raise NotFoundError("Trainee profile not found.")
        if payload.goal is not None:
            trainee.goal = payload.goal
        if payload.height_cm is not None:
            trainee.height_cm = payload.height_cm
        if payload.weight_kg is not None:
            trainee.weight_kg = payload.weight_kg
        if payload.daily_calorie_target is not None:
            trainee.daily_calorie_target = payload.daily_calorie_target
        return trainee_out(trainee)

    def link_trainer(self, trainee_id: str, invite_code: str) -> TraineeProfileOut:
        trainee = self.trainees.get(trainee_id)
        if trainee is None:
            raise ValidationAppError("Only trainees can join a trainer.")
        trainer = self.trainers.get_by_invite_code(invite_code.strip())
        if trainer is None:
            raise ValidationAppError("Invite code not found.")
        trainee.trainer_id = trainer.id
        return trainee_out(trainee)

    def my_trainer(self, trainee_id: str) -> TrainerPublic | None:
        trainee = self.trainees.get(trainee_id)
        if trainee is None or not trainee.trainer_id:
            return None
        trainer = self.trainers.get_with_user(trainee.trainer_id)
        if trainer is None:
            return None
        return TrainerPublic(trainer=trainer_out(trainer), user=user_public(trainer.user))

    def assigned_plan(self, trainee_id: str) -> WorkoutPlanOut | None:
        assignment = self.assignments.get_for_trainee(trainee_id)
        if assignment is None or assignment.plan is None:
            return None
        return plan_out(assignment.plan)

    def list_logs(self, trainee_id: str) -> list[WorkoutLogOut]:
        return [workout_log_out(log) for log in self.logs.list_for_trainee(trainee_id)]

    def save_log(self, trainee_id: str, payload: CreateWorkoutLogRequest) -> WorkoutLogOut:
        if self.plans.get(payload.plan_id) is None:
            raise NotFoundError("Workout plan not found.")
        for item in payload.sets:
            if self.exercises.get(item.exercise_id) is None:
                raise ValidationAppError(f"Unknown exercise: {item.exercise_id}")
        log = models.WorkoutLog(
            id=str(uuid4()),
            trainee_id=trainee_id,
            plan_id=payload.plan_id,
            completed_at=payload.completed_at or _utc_now(),
            duration_minutes=payload.duration_minutes,
            sets=[
                models.WorkoutSetLog(
                    id=item.id or str(uuid4()),
                    exercise_id=item.exercise_id,
                    set_number=item.set_number,
                    reps=item.reps,
                    weight_kg=item.weight_kg,
                )
                for item in payload.sets
            ],
        )
        return workout_log_out(self.logs.add(log))

    def list_meals(self, trainee_id: str, on_date: date | None) -> list[MealOut]:
        return [meal_out(meal) for meal in self.meals.list_for_trainee(trainee_id, on=on_date)]

    def save_meal(self, trainee_id: str, payload: CreateMealRequest) -> MealOut:
        name = payload.name.strip()
        if not name:
            raise ValidationAppError("Enter a meal name.")
        meal = models.Meal(
            id=str(uuid4()),
            trainee_id=trainee_id,
            name=name,
            eaten_at=payload.eaten_at or _utc_now(),
            portion_grams=payload.portion_grams,
            calories=payload.macros.calories,
            protein=payload.macros.protein,
            carbs=payload.macros.carbs,
            fat=payload.macros.fat,
            source=payload.source,
            is_estimate=payload.is_estimate,
        )
        return meal_out(self.meals.add(meal))

    def daily_macros(self, trainee_id: str, on_date: date) -> DailyMacrosResponse:
        meals = self.list_meals(trainee_id, on_date)
        return DailyMacrosResponse(
            trainee_id=trainee_id,
            date=on_date.isoformat(),
            macros=MacroEstimateOut(
                calories=sum(meal.macros.calories for meal in meals),
                protein=sum(meal.macros.protein for meal in meals),
                carbs=sum(meal.macros.carbs for meal in meals),
                fat=sum(meal.macros.fat for meal in meals),
            ),
            meals=meals,
        )

    def list_feedback(self, trainee_id: str) -> list[TrainerFeedbackOut]:
        return [feedback_out(item) for item in self.coaching.list_feedback(trainee_id)]

    def list_form_reports(self, trainee_id: str) -> list[FormReportOut]:
        return [form_report_out(report) for report in self.coaching.list_form_reports(trainee_id)]

    def save_form_report(self, trainee_id: str, payload: CreateFormReportRequest) -> FormReportOut:
        if self.exercises.get(payload.exercise_id) is None:
            raise NotFoundError("Exercise not found.")
        report = models.FormReport(
            id=str(uuid4()),
            trainee_id=trainee_id,
            exercise_id=payload.exercise_id,
            created_at=payload.created_at or _utc_now(),
            score=payload.score,
            cues=payload.cues,
            rep_count=payload.rep_count,
        )
        return form_report_out(self.coaching.add_form_report(report))

    def lookup_food(self, query: str):
        food = self.foods.lookup(query)
        return food_out(food) if food else None
