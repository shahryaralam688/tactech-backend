from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationAppError
from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.coaching import CoachingRepository
from app.repositories.exercise import ExerciseRepository
from app.repositories.meal import MealRepository
from app.repositories.plan import PlanRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.workout_log import WorkoutLogRepository
from app.schemas.common import MealOut, TrainerFeedbackOut, WorkoutPlanOut
from app.schemas.mappers import (
    assignment_out,
    feedback_out,
    form_report_out,
    meal_out,
    plan_out,
    trainer_out,
    trainee_out,
    user_public,
    workout_log_out,
)
from app.schemas.requests import (
    WEEKDAYS,
    AssignPlanRequest,
    CreateFeedbackRequest,
    CreatePlanRequest,
    PlanDayExerciseIn,
    PlanDayIn,
    UpdateTrainerProfileRequest,
    WorkoutExerciseIn,
)
from app.schemas.responses import AssignmentResponse, TraineeRosterItem, TrainerPublic
from app.services.access import require_owned_trainee


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TrainerService:
    def __init__(self, db: Session) -> None:
        self.trainers = TrainerRepository(db)
        self.trainees = TraineeRepository(db)
        self.plans = PlanRepository(db)
        self.assignments = AssignmentRepository(db)
        self.logs = WorkoutLogRepository(db)
        self.meals = MealRepository(db)
        self.coaching = CoachingRepository(db)
        self.exercises = ExerciseRepository(db)

    def update_profile(self, trainer_id: str, payload: UpdateTrainerProfileRequest) -> TrainerPublic:
        trainer = self.trainers.get_with_user(trainer_id)
        if trainer is None:
            raise NotFoundError("Trainer profile not found.")
        if payload.specialty is not None:
            trainer.specialty = payload.specialty
        if payload.years_experience is not None:
            trainer.years_experience = payload.years_experience
        if payload.bio is not None:
            trainer.bio = payload.bio
        return TrainerPublic(trainer=trainer_out(trainer), user=user_public(trainer.user))

    def list_trainees(self, trainer_id: str) -> list[TraineeRosterItem]:
        items = []
        for trainee in self.trainees.list_for_trainer(trainer_id):
            assignment = self.assignments.get_for_trainee(trainee.id)
            items.append(
                TraineeRosterItem(
                    **trainee_out(trainee).model_dump(),
                    user=user_public(trainee.user),
                    assigned_plan=plan_out(assignment.plan) if assignment and assignment.plan else None,
                )
            )
        return items

    def get_trainee(self, trainer_id: str, trainee_id: str) -> TraineeRosterItem:
        trainee = require_owned_trainee(self.trainees, trainer_id, trainee_id)
        loaded = self.trainees.get_with_user(trainee.id)
        if loaded is None:
            raise NotFoundError("Trainee not found.")
        assignment = self.assignments.get_for_trainee(loaded.id)
        return TraineeRosterItem(
            **trainee_out(loaded).model_dump(),
            user=user_public(loaded.user),
            assigned_plan=plan_out(assignment.plan) if assignment and assignment.plan else None,
        )

    def list_plans(self, trainer_id: str) -> list[WorkoutPlanOut]:
        return [plan_out(plan) for plan in self.plans.list_for_trainer(trainer_id)]

    def get_plan(self, trainer_id: str, plan_id: str) -> WorkoutPlanOut:
        plan = self.plans.get(plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        return plan_out(plan)

    def create_plan(self, trainer_id: str, payload: CreatePlanRequest) -> WorkoutPlanOut:
        plan = models.WorkoutPlan(
            id=str(uuid4()),
            trainer_id=trainer_id,
            title="",
            focus="",
            duration_minutes=payload.duration_minutes,
            level=payload.level,
            days_per_week=payload.days_per_week,
        )
        self._apply_plan_payload(plan, payload)
        self.plans.add(plan)
        loaded = self.plans.get(plan.id)
        return plan_out(loaded or plan)

    def update_plan(self, trainer_id: str, plan_id: str, payload: CreatePlanRequest) -> WorkoutPlanOut:
        plan = self.plans.get(plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        plan.exercises.clear()
        plan.days.clear()
        self._apply_plan_payload(plan, payload)
        loaded = self.plans.get(plan.id)
        return plan_out(loaded or plan)

    def _apply_plan_payload(self, plan: models.WorkoutPlan, payload: CreatePlanRequest) -> None:
        title = payload.title.strip()
        if not title:
            raise ValidationAppError("Enter a plan title.")
        days = payload.days or []
        flat_in = payload.exercises or []
        day_exercises = [item for day in days for item in day.exercises]
        if not days and not flat_in:
            raise ValidationAppError("Add at least one exercise.")
        self._validate_exercises(flat_in)
        self._validate_day_exercises(day_exercises)
        for day in days:
            weekday = day.weekday.strip().lower()
            if weekday not in WEEKDAYS:
                raise ValidationAppError("Weekday must be monday through sunday.")

        plan.title = title
        plan.focus = payload.focus.strip()
        plan.duration_minutes = payload.duration_minutes
        plan.level = payload.level
        plan.days_per_week = payload.days_per_week
        plan.notes = payload.notes.strip() if payload.notes else None
        plan.days = [self._build_day(day, index) for index, day in enumerate(days)]
        plan.exercises = self._flatten_exercises(days, flat_in)

    def _build_day(self, day: PlanDayIn, index: int) -> models.PlanDay:
        return models.PlanDay(
            id=day.id or str(uuid4()),
            weekday=day.weekday.strip().lower(),
            start_time=day.start_time,
            title=day.title.strip(),
            focus=day.focus.strip(),
            duration_minutes=day.duration_minutes,
            location=day.location,
            warmup=day.warmup,
            cooldown=day.cooldown,
            coach_notes=day.coach_notes,
            sort_order=index,
            exercises=[self._build_day_exercise(item, ex_index) for ex_index, item in enumerate(day.exercises)],
        )

    def _build_day_exercise(self, item: PlanDayExerciseIn, index: int) -> models.PlanExercise:
        return models.PlanExercise(
            id=item.id or str(uuid4()),
            exercise_id=item.exercise_id,
            sort_order=index,
            sets=item.sets,
            reps=item.reps,
            rest_seconds=item.rest_seconds,
            recommended_weight_kg=item.recommended_weight_kg,
            tempo=item.tempo,
            rpe=item.rpe,
            notes=item.notes,
            side=item.side,
            prescribed_sets=[
                models.PlanPrescribedSet(
                    id=row.id or str(uuid4()),
                    set_number=row.set_number,
                    reps=row.reps,
                    weight_kg=row.weight_kg,
                    rpe=row.rpe,
                )
                for row in item.prescribed_sets
            ],
        )

    def _flatten_exercises(
        self,
        days: list[PlanDayIn],
        flat_in: list[WorkoutExerciseIn],
    ) -> list[models.WorkoutExercise]:
        source: list[WorkoutExerciseIn] = []
        if days:
            for day in days:
                for item in day.exercises:
                    source.append(
                        WorkoutExerciseIn(
                            exercise_id=item.exercise_id,
                            sets=item.sets,
                            reps=item.reps,
                            rest_seconds=item.rest_seconds,
                            recommended_weight_kg=item.recommended_weight_kg,
                        )
                    )
        else:
            source = flat_in
        return [
            models.WorkoutExercise(
                id=item.id or str(uuid4()),
                exercise_id=item.exercise_id,
                sets=item.sets,
                reps=item.reps,
                rest_seconds=item.rest_seconds,
                recommended_weight_kg=item.recommended_weight_kg,
                sort_order=index,
            )
            for index, item in enumerate(source)
        ]

    def assign_plan(self, trainer_id: str, payload: AssignPlanRequest) -> AssignmentResponse:
        require_owned_trainee(self.trainees, trainer_id, payload.trainee_id)
        plan = self.plans.get(payload.plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        assignment = models.PlanAssignment(
            id=str(uuid4()),
            plan_id=plan.id,
            trainee_id=payload.trainee_id,
            assigned_at=_utc_now(),
        )
        self.assignments.replace(assignment)
        return AssignmentResponse(assignment=assignment_out(assignment), plan=plan_out(plan))

    def trainee_meals(self, trainer_id: str, trainee_id: str, on_date) -> list[MealOut]:
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [meal_out(meal) for meal in self.meals.list_for_trainee(trainee_id, on=on_date)]

    def trainee_macros(self, trainer_id: str, trainee_id: str, on_date):
        meals = self.trainee_meals(trainer_id, trainee_id, on_date)
        return _sum_macros(meals)

    def trainee_logs(self, trainer_id: str, trainee_id: str):
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [workout_log_out(log) for log in self.logs.list_for_trainee(trainee_id)]

    def trainee_form_reports(self, trainer_id: str, trainee_id: str):
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [form_report_out(report) for report in self.coaching.list_form_reports(trainee_id)]

    def trainee_feedback(self, trainer_id: str, trainee_id: str):
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [feedback_out(item) for item in self.coaching.list_feedback(trainee_id)]

    def save_feedback(self, trainer_id: str, payload: CreateFeedbackRequest) -> TrainerFeedbackOut:
        require_owned_trainee(self.trainees, trainer_id, payload.trainee_id)
        message = payload.message.strip()
        if not message:
            raise ValidationAppError("Write a note for this trainee.")
        if payload.related_exercise_id and self.exercises.get(payload.related_exercise_id) is None:
            raise NotFoundError("Exercise not found.")
        item = models.TrainerFeedback(
            id=str(uuid4()),
            trainer_id=trainer_id,
            trainee_id=payload.trainee_id,
            message=message,
            created_at=_utc_now(),
            related_exercise_id=payload.related_exercise_id,
        )
        return feedback_out(self.coaching.add_feedback(item))

    def _validate_exercises(self, drafts: list[WorkoutExerciseIn]) -> None:
        for item in drafts:
            if self.exercises.get(item.exercise_id) is None:
                raise ValidationAppError(f"Unknown exercise: {item.exercise_id}")

    def _validate_day_exercises(self, drafts: list[PlanDayExerciseIn]) -> None:
        for item in drafts:
            if self.exercises.get(item.exercise_id) is None:
                raise ValidationAppError(f"Unknown exercise: {item.exercise_id}")


def _sum_macros(meals: list[MealOut]):
    from app.schemas.common import MacroEstimateOut

    return MacroEstimateOut(
        calories=sum(meal.macros.calories for meal in meals),
        protein=sum(meal.macros.protein for meal in meals),
        carbs=sum(meal.macros.carbs for meal in meals),
        fat=sum(meal.macros.fat for meal in meals),
    )
