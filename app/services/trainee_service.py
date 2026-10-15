from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
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
    CreatePlanRequest,
    CreateWorkoutLogRequest,
    UpdateMealRequest,
    UpdatePlanRequest,
    UpdateTraineeProfileRequest,
    UpdateWorkoutLogRequest,
)
from app.schemas.responses import DailyMacrosResponse, TrainerPublic
from app.schemas.roster import UnlinkOut
from app.services.roster_link_service import RosterLinkService
from app.services.push_service import PushService
from app.realtime.chat_hub import chat_hub

log = get_logger("tactech.trainee")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TraineeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.trainees = TraineeRepository(db)
        self.trainers = TrainerRepository(db)
        self.assignments = AssignmentRepository(db)
        self.plans = PlanRepository(db)
        self.logs = WorkoutLogRepository(db)
        self.meals = MealRepository(db)
        self.coaching = CoachingRepository(db)
        self.exercises = ExerciseRepository(db)
        self.foods = FoodRepository(db)
        self.roster = RosterLinkService(db)
        self.push = PushService(db, hub=chat_hub)

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
        user = self.users.get(trainee.user_id)
        if user is not None:
            from app.services.user_gates import maybe_mark_onboarding_completed

            maybe_mark_onboarding_completed(self.db, user, trainee=trainee)
        return trainee_out(trainee)

    def link_trainer(self, trainee_id: str, invite_code: str):
        """Deprecated instant-link — delegates to join-request create (pending only)."""
        from app.schemas.join_requests import JoinRequestCreate
        from app.services.join_request_service import JoinRequestService

        trainee = self.trainees.get(trainee_id)
        if trainee is None:
            raise ValidationAppError("Only trainees can join a trainer.")
        return JoinRequestService(self.db).create(
            trainee_id=trainee_id,
            trainee_user_id=trainee.user_id,
            payload=JoinRequestCreate(invite_code=invite_code, message=None),
        )

    def unlink_trainer(self, trainee_id: str) -> UnlinkOut:
        """Trainee leaves active trainer. Accepts no body. Clears plan; keeps chat."""
        trainee = self.trainees.get_with_user(trainee_id)
        if trainee is None:
            log.info(
                "trainee_unlink_denied",
                status_code=404,
                user_id=None,
                trainee_id=trainee_id,
                reason="no_profile",
            )
            raise NotFoundError("Trainee profile not found.")

        active = self.roster.links.get_active_for_trainee(trainee.id)
        if not trainee.trainer_id and active is None:
            log.info(
                "trainee_unlink_denied",
                status_code=404,
                user_id=trainee.user_id,
                trainee_id=trainee.id,
                reason="no_link",
            )
            raise NotFoundError("No trainer linked.")

        trainer_user_id: str | None = None
        if active is not None:
            trainer_user_id = active.trainer_user_id
        elif trainee.trainer_id:
            trainer = self.trainers.get(trainee.trainer_id)
            trainer_user_id = trainer.user_id if trainer else None

        trainee_name = trainee.user.name if trainee.user else "A trainee"

        ended = self.roster.end_active(
            trainee=trainee,
            ended_by_user_id=trainee.user_id,
        )
        # Ensure denormalized pointer cleared even if end_active returned None
        if trainee.trainer_id is not None:
            trainee.trainer_id = None
            self.db.add(trainee)
            self.db.flush()

        ended_at = ended.ended_at if ended and ended.ended_at else _utc_now()
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)
        if ended is not None:
            trainer_user_id = ended.trainer_user_id or trainer_user_id

        if trainer_user_id:
            try:
                self.push.notify_relationship_ended_sync(
                    peer_user_id=trainer_user_id,
                    actor_user_id=trainee.user_id,
                    reason="trainee_left",
                    title="Trainee left",
                    body=f"{trainee_name} left your coaching roster.",
                    trainer_user_id=trainer_user_id,
                    trainee_user_id=trainee.user_id,
                    trainee_profile_id=trainee.id,
                    trainee_name=trainee_name,
                    occurred_at=ended_at.isoformat().replace("+00:00", "Z"),
                )
            except Exception:
                log.exception("trainee_left_notify_failed", trainee_id=trainee.id)

        log.info(
            "trainee_unlinked",
            status_code=200,
            user_id=trainee.user_id,
            trainee_id=trainee.id,
            trainer_user_id=trainer_user_id,
        )
        return UnlinkOut(ok=True, ended_at=ended_at, trainer_user_id=trainer_user_id)

    def my_trainer(self, trainee_id: str) -> TrainerPublic | None:
        """Return linked trainer, or null when unlinked (never 500)."""
        trainee = self.trainees.get(trainee_id)
        if trainee is None or not trainee.trainer_id:
            return None
        trainer = self.trainers.get_with_user(trainee.trainer_id)
        if trainer is None:
            return None
        return TrainerPublic(trainer=trainer_out(trainer), user=user_public(trainer.user))

    def assigned_plan(self, trainee_id: str) -> WorkoutPlanOut | None:
        assignment = self.assignments.get_for_trainee(trainee_id)
        if assignment is None or assignment.plan is None or assignment.plan.deleted_at is not None:
            return None
        return plan_out(assignment.plan)

    def _require_owned_ai_plan(self, trainee_id: str, plan_id: str) -> models.WorkoutPlan:
        plan = self.plans.get(plan_id)
        if plan is None or plan.deleted_at is not None:
            raise NotFoundError("Workout plan not found.")

        owns = plan.owner_trainee_id == trainee_id
        assignment = self.assignments.get_for_trainee(trainee_id)
        if assignment is not None and assignment.plan_id == plan_id:
            owns = True
        if not owns:
            raise ForbiddenError("You do not own this plan.", code="FORBIDDEN")

        source = getattr(plan, "source", None) or ("ai" if not plan.trainer_id else "trainer")
        if source != "ai":
            raise ForbiddenError(
                "This plan was assigned by your trainer and can’t be edited or deleted.",
                code="PLAN_LOCKED",
            )
        return plan

    def update_ai_plan(
        self, trainee_id: str, plan_id: str, payload: UpdatePlanRequest
    ) -> WorkoutPlanOut:
        """PATCH AI solo plan — trainer plans → 403 PLAN_LOCKED."""
        plan = self._require_owned_ai_plan(trainee_id, plan_id)
        from app.services.trainer_service import TrainerService

        ts = TrainerService(self.db)
        data = payload.model_dump(exclude_unset=True)
        full_replace = all(
            key in data for key in ("title", "focus", "duration_minutes", "level", "days_per_week")
        ) and ("days" in data or "exercises" in data)
        if full_replace:
            create_shaped = CreatePlanRequest(
                title=payload.title or plan.title,
                focus=payload.focus if payload.focus is not None else plan.focus,
                duration_minutes=payload.duration_minutes or plan.duration_minutes,
                level=payload.level or plan.level,
                days_per_week=payload.days_per_week or plan.days_per_week,
                notes=payload.notes if payload.notes is not None else plan.notes,
                exercises=payload.exercises or [],
                days=payload.days or [],
            )
            plan.days.clear()
            plan.exercises.clear()
            ts._apply_plan_payload(plan, create_shaped)
        else:
            # Reuse trainer update path without trainer_id ownership by applying fields here
            if payload.title is not None:
                title = payload.title.strip()
                if not title:
                    raise ValidationAppError("Enter a plan title.")
                plan.title = title
            if payload.focus is not None:
                plan.focus = payload.focus.strip()
            if payload.duration_minutes is not None:
                plan.duration_minutes = payload.duration_minutes
            if payload.level is not None:
                plan.level = payload.level
            if payload.days_per_week is not None:
                plan.days_per_week = payload.days_per_week
            if payload.notes is not None:
                plan.notes = payload.notes.strip() or None
            if payload.days is not None or payload.exercises is not None:
                create_shaped = CreatePlanRequest(
                    title=plan.title,
                    focus=plan.focus,
                    duration_minutes=plan.duration_minutes,
                    level=plan.level,
                    days_per_week=plan.days_per_week,
                    notes=plan.notes,
                    exercises=payload.exercises or [],
                    days=payload.days or [],
                )
                if payload.days is not None:
                    plan.days.clear()
                if payload.days is not None or payload.exercises is not None:
                    plan.exercises.clear()
                ts._apply_plan_payload(plan, create_shaped)

        plan.source = "ai"
        plan.owner_trainee_id = trainee_id
        plan.trainer_id = None
        self.db.add(plan)
        self.db.commit()
        loaded = self.plans.get(plan.id)
        return plan_out(loaded or plan)

    def delete_ai_plan(self, trainee_id: str, plan_id: str) -> None:
        """Soft-delete AI solo plan and clear this trainee’s assignment."""
        plan = self._require_owned_ai_plan(trainee_id, plan_id)
        plan.deleted_at = _utc_now()
        self.db.add(plan)
        assignment = self.assignments.get_for_trainee(trainee_id)
        if assignment is not None and assignment.plan_id == plan_id:
            self.assignments.delete(assignment)
        self.db.commit()

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

    def update_meal(self, trainee_id: str, meal_id: str, payload: UpdateMealRequest) -> MealOut:
        meal = self.meals.get(meal_id)
        if meal is None or meal.trainee_id != trainee_id:
            raise NotFoundError("Meal not found.")
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise ValidationAppError("Enter a meal name.")
            meal.name = name
        if payload.eaten_at is not None:
            meal.eaten_at = payload.eaten_at
        if payload.portion_grams is not None:
            meal.portion_grams = payload.portion_grams
        if payload.macros is not None:
            meal.calories = payload.macros.calories
            meal.protein = payload.macros.protein
            meal.carbs = payload.macros.carbs
            meal.fat = payload.macros.fat
        if payload.source is not None:
            meal.source = payload.source
        if payload.is_estimate is not None:
            meal.is_estimate = payload.is_estimate
        return meal_out(meal)

    def delete_meal(self, trainee_id: str, meal_id: str) -> None:
        meal = self.meals.get(meal_id)
        if meal is None or meal.trainee_id != trainee_id:
            raise NotFoundError("Meal not found.")
        self.meals.delete(meal)

    def update_log(self, trainee_id: str, log_id: str, payload: UpdateWorkoutLogRequest) -> WorkoutLogOut:
        log = self.logs.get(log_id)
        if log is None or log.trainee_id != trainee_id:
            raise NotFoundError("Workout log not found.")
        if payload.plan_id is not None:
            if self.plans.get(payload.plan_id) is None:
                raise NotFoundError("Workout plan not found.")
            log.plan_id = payload.plan_id
        if payload.completed_at is not None:
            log.completed_at = payload.completed_at
        if payload.duration_minutes is not None:
            log.duration_minutes = payload.duration_minutes
        if payload.sets is not None:
            for item in payload.sets:
                if self.exercises.get(item.exercise_id) is None:
                    raise ValidationAppError(f"Unknown exercise: {item.exercise_id}")
            log.sets.clear()
            log.sets = [
                models.WorkoutSetLog(
                    id=item.id or str(uuid4()),
                    exercise_id=item.exercise_id,
                    set_number=item.set_number,
                    reps=item.reps,
                    weight_kg=item.weight_kg,
                )
                for item in payload.sets
            ]
        loaded = self.logs.get(log.id)
        return workout_log_out(loaded or log)

    def delete_log(self, trainee_id: str, log_id: str) -> None:
        log = self.logs.get(log_id)
        if log is None or log.trainee_id != trainee_id:
            raise NotFoundError("Workout log not found.")
        self.logs.delete(log)

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
