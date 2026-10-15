from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.coaching import CoachingRepository
from app.repositories.exercise import ExerciseRepository
from app.repositories.meal import MealRepository
from app.repositories.plan import PlanRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.trainer import TrainerRepository
from app.repositories.user import UserRepository
from app.repositories.workout_log import WorkoutLogRepository
from app.schemas.assessment import TrainerAssessmentOut
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
    TrainerAssessmentRequest,
    UpdatePlanRequest,
    UpdateTrainerProfileRequest,
    WorkoutExerciseIn,
)
from app.schemas.responses import (
    AssignmentResponse,
    TraineeAnalyticsDay,
    TraineeAnalyticsOut,
    TraineeExerciseStat,
    TraineeRosterItem,
    TrainerPublic,
)
from app.schemas.roster import RemoveTraineeOut
from app.services.access import require_owned_trainee
from app.services.roster_link_service import RosterLinkService
from app.services.push_service import PushService
from app.realtime.chat_hub import chat_hub

log = get_logger("tactech.trainer")


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
        self.users = UserRepository(db)
        self.db = db
        self.roster = RosterLinkService(db)
        self.push = PushService(db, hub=chat_hub)

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
        from app.services.user_gates import maybe_mark_onboarding_completed

        maybe_mark_onboarding_completed(self.db, trainer.user, trainer=trainer)
        return TrainerPublic(trainer=trainer_out(trainer), user=user_public(trainer.user))

    def list_trainees(self, trainer_id: str) -> list[TraineeRosterItem]:
        items = []
        for trainee in self.trainees.list_for_trainer(trainer_id):
            assignment = self.assignments.get_for_trainee(trainee.id)
            assigned_plan = None
            if assignment and assignment.plan and assignment.plan.deleted_at is None:
                # Assessment / legacy plans may have trainer_id=null — still show on roster.
                if assignment.plan.trainer_id is None:
                    assignment.plan.trainer_id = trainer_id
                    self.db.add(assignment.plan)
                try:
                    assigned_plan = plan_out(assignment.plan)
                except Exception:
                    log.exception(
                        "list_trainees_plan_out_failed",
                        trainee_id=trainee.id,
                        plan_id=assignment.plan_id,
                    )
                    assigned_plan = None
            items.append(
                TraineeRosterItem(
                    **trainee_out(trainee).model_dump(),
                    user=user_public(trainee.user),
                    assigned_plan=assigned_plan,
                )
            )
        return items

    def remove_trainee(self, trainer_id: str, trainee_id: str) -> RemoveTraineeOut:
        """Trainer removes trainee from roster — soft-end link, clear plan, keep chat.

        ``trainee_id`` may be trainee profile id or trainee user id (iOS may send either).
        """
        trainer = self.trainers.get(trainer_id)
        if trainer is None:
            log.info(
                "trainer_remove_denied",
                status_code=404,
                user_id=None,
                trainer_id=trainer_id,
                trainee_id=trainee_id,
                reason="no_trainer",
            )
            raise NotFoundError("Trainer profile not found.")

        resolved = self.trainees.get(trainee_id) or self.trainees.get_by_user_id(trainee_id)
        if resolved is None:
            log.info(
                "trainer_remove_denied",
                status_code=404,
                user_id=trainer.user_id,
                trainer_id=trainer_id,
                trainee_id=trainee_id,
                reason="trainee_not_found",
            )
            raise NotFoundError("Trainee not found.")

        try:
            require_owned_trainee(self.trainees, trainer_id, resolved.id)
        except (ForbiddenError, NotFoundError):
            log.info(
                "trainer_remove_denied",
                status_code=403,
                user_id=trainer.user_id,
                trainer_id=trainer_id,
                trainee_id=resolved.id,
                reason="not_on_roster",
            )
            raise

        loaded = self.trainees.get_with_user(resolved.id) or resolved

        ended = self.roster.end_active(
            trainee=loaded,
            ended_by_user_id=trainer.user_id,
            expected_trainer_id=trainer_id,
        )
        if loaded.trainer_id is not None:
            loaded.trainer_id = None
            self.db.add(loaded)
            self.db.flush()

        ended_at = ended.ended_at if ended and ended.ended_at else _utc_now()
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)

        trainer_name = "Your trainer"
        user = self.users.get(trainer.user_id)
        if user is not None:
            trainer_name = user.name

        try:
            self.push.notify_relationship_ended_sync(
                peer_user_id=loaded.user_id,
                actor_user_id=trainer.user_id,
                reason="trainer_removed",
                title="Removed by trainer",
                body=f"{trainer_name} removed you from their roster.",
                trainer_user_id=trainer.user_id,
                trainee_user_id=loaded.user_id,
                trainee_profile_id=loaded.id,
                trainer_name=trainer_name,
                occurred_at=ended_at.isoformat().replace("+00:00", "Z"),
            )
        except Exception:
            log.exception("trainer_removed_notify_failed", trainee_id=loaded.id)

        log.info(
            "trainee_removed",
            status_code=200,
            user_id=trainer.user_id,
            trainer_id=trainer_id,
            trainee_id=loaded.id,
        )
        return RemoveTraineeOut(ok=True, trainee_id=loaded.id, ended_at=ended_at)

    def get_trainee(self, trainer_id: str, trainee_id: str) -> TraineeRosterItem:
        trainee = require_owned_trainee(self.trainees, trainer_id, trainee_id)
        loaded = self.trainees.get_with_user(trainee.id)
        if loaded is None:
            raise NotFoundError("Trainee not found.")
        assignment = self.assignments.get_for_trainee(loaded.id)
        return TraineeRosterItem(
            **trainee_out(loaded).model_dump(),
            user=user_public(loaded.user),
            assigned_plan=(
                plan_out(assignment.plan)
                if assignment and assignment.plan and assignment.plan.deleted_at is None
                else None
            ),
        )

    def list_plans(self, trainer_id: str) -> list[WorkoutPlanOut]:
        return [plan_out(plan) for plan in self.plans.list_for_trainer(trainer_id)]

    def get_plan(self, trainer_id: str, plan_id: str) -> WorkoutPlanOut:
        plan = self.plans.get(plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        return plan_out(plan)

    def create_plan(self, trainer_id: str, payload: CreatePlanRequest) -> WorkoutPlanOut:
        plan_id = payload.id or str(uuid4())
        if self.plans.get(plan_id, include_deleted=True):
            raise ConflictError("A plan with this id already exists.")
        plan = models.WorkoutPlan(
            id=plan_id,
            trainer_id=trainer_id,
            source="trainer",
            owner_trainee_id=None,
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

    def update_plan(self, trainer_id: str, plan_id: str, payload: UpdatePlanRequest) -> WorkoutPlanOut:
        """Full replace of provided fields. iOS sends full PlanBody; assignments stay linked."""
        plan = self.plans.get(plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        if (getattr(plan, "source", None) or "trainer") == "ai":
            raise ForbiddenError(
                "AI solo plans can only be edited by the trainee who owns them.",
                code="PLAN_LOCKED",
            )
        assignees = self.assignments.list_for_plan(plan.id)
        # When client sends a full create-shaped body (all core fields + schedule),
        # reuse create validation path for consistency.
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
            self._apply_plan_payload(plan, create_shaped)
            loaded = self.plans.get(plan.id)
            out = plan_out(loaded or plan)
            self._notify_assignees_plan_updated(trainer_id, loaded or plan, assignees)
            return out

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
            days = payload.days if payload.days is not None else []
            flat_in = payload.exercises if payload.exercises is not None else []
            if payload.days is not None:
                for day in days:
                    weekday = day.weekday.strip().lower()
                    if weekday not in WEEKDAYS:
                        raise ValidationAppError("Weekday must be monday through sunday.")
                self._validate_day_exercises([item for day in days for item in day.exercises])
                plan.days.clear()
                plan.days = [self._build_day(day, index) for index, day in enumerate(days)]
            if payload.days is not None or payload.exercises is not None:
                if payload.exercises is not None:
                    self._validate_exercises(flat_in)
                plan.exercises.clear()
                plan.exercises = self._flatten_exercises(
                    days if payload.days is not None else [],
                    flat_in if payload.exercises is not None else [],
                )
        loaded = self.plans.get(plan.id)
        out = plan_out(loaded or plan)
        self._notify_assignees_plan_updated(trainer_id, loaded or plan, assignees)
        return out

    def delete_plan(self, trainer_id: str, plan_id: str) -> None:
        """Soft-delete plan and clear active assignments. Workout logs are preserved."""
        plan = self.plans.get(plan_id)
        if plan is None or plan.trainer_id != trainer_id:
            raise NotFoundError("Workout plan not found.")
        if (getattr(plan, "source", None) or "trainer") == "ai":
            raise ForbiddenError(
                "AI solo plans can only be deleted by the trainee who owns them.",
                code="PLAN_LOCKED",
            )
        plan_title = plan.title
        plan.deleted_at = _utc_now()
        cleared = self.assignments.clear_for_plan(plan.id)
        trainer = self.trainers.get(trainer_id)
        trainer_user_id = trainer.user_id if trainer else ""
        for row in cleared:
            trainee = row.trainee or self.trainees.get(row.trainee_id)
            if trainee is None:
                continue
            self._notify_plan(
                action="unassigned",
                trainer_id=trainer_id,
                trainer_user_id=trainer_user_id,
                trainee=trainee,
                plan_id=plan_id,
                plan_title=plan_title,
            )

    def unassign_plan(
        self,
        trainer_id: str,
        assignment_id: str | None = None,
        plan_id: str | None = None,
        trainee_id: str | None = None,
    ) -> None:
        """Remove active assignment. Idempotent: missing assignment → no-op (204)."""
        assignment = None
        if assignment_id:
            assignment = self.assignments.get(assignment_id)
        elif plan_id and trainee_id:
            assignment = self.assignments.get_by_plan_and_trainee(plan_id, trainee_id)
        if assignment is None:
            # Idempotent DELETE — iOS may retry; still verify roster when ids provided.
            if trainee_id:
                require_owned_trainee(self.trainees, trainer_id, trainee_id)
            return
        require_owned_trainee(self.trainees, trainer_id, assignment.trainee_id)
        plan = self.plans.get(assignment.plan_id, include_deleted=True)
        if plan is not None and plan.trainer_id and plan.trainer_id != trainer_id:
            raise NotFoundError("Assignment not found.")
        trainee = assignment.trainee or self.trainees.get(assignment.trainee_id)
        cleared_plan_id = assignment.plan_id
        cleared_title = plan.title if plan is not None else "workout plan"
        self.assignments.delete(assignment)
        if trainee is not None:
            trainer = self.trainers.get(trainer_id)
            self._notify_plan(
                action="unassigned",
                trainer_id=trainer_id,
                trainer_user_id=trainer.user_id if trainer else "",
                trainee=trainee,
                plan_id=cleared_plan_id,
                plan_title=cleared_title,
            )

    def save_trainer_assessment(
        self,
        trainer_id: str,
        payload: TrainerAssessmentRequest,
    ) -> TrainerAssessmentOut:
        trainer = self.trainers.get(trainer_id)
        if trainer is None:
            raise NotFoundError("Trainer profile not found.")
        trainer.specialty = payload.specialty.strip() or trainer.specialty
        trainer.years_experience = payload.years_experience
        trainer.bio = payload.bio.strip() or trainer.bio
        user = self.users.get(trainer.user_id)
        if user is not None:
            user.gender = payload.gender.strip() or user.gender
            if payload.bio.strip():
                user.bio = payload.bio.strip()
            from app.services.user_gates import mark_assessment_completed

            mark_assessment_completed(self.db, user)
        row = models.TrainerAssessment(
            id=str(uuid4()),
            trainer_id=trainer_id,
            created_at=_utc_now(),
            payload=payload.model_dump(by_alias=True),
        )
        self.db.add(row)
        self.db.flush()
        return TrainerAssessmentOut(
            id=row.id,
            trainer_id=trainer_id,
            coaching_focus=payload.coaching_focus,
            years_experience=payload.years_experience,
            certifications=payload.certifications,
            specialty=payload.specialty,
            client_types=payload.client_types,
            max_clients=payload.max_clients,
            session_style=payload.session_style,
            days_per_week=payload.days_per_week,
            training_modes=payload.training_modes,
            gender=payload.gender,
            bio=payload.bio,
            philosophy=payload.philosophy,
            created_at=row.created_at,
        )

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
        trainee = self.trainees.get(payload.trainee_id)
        trainer = self.trainers.get(trainer_id)
        if trainee is not None and trainer is not None:
            self._notify_plan(
                action="assigned",
                trainer_id=trainer_id,
                trainer_user_id=trainer.user_id,
                trainee=trainee,
                plan_id=plan.id,
                plan_title=plan.title,
            )
        return AssignmentResponse(assignment=assignment_out(assignment), plan=plan_out(plan))

    def _notify_assignees_plan_updated(
        self,
        trainer_id: str,
        plan: models.WorkoutPlan,
        assignees: list[models.PlanAssignment],
    ) -> None:
        if not assignees:
            return
        trainer = self.trainers.get(trainer_id)
        trainer_user_id = trainer.user_id if trainer else ""
        for row in assignees:
            trainee = row.trainee or self.trainees.get(row.trainee_id)
            if trainee is None:
                continue
            self._notify_plan(
                action="updated",
                trainer_id=trainer_id,
                trainer_user_id=trainer_user_id,
                trainee=trainee,
                plan_id=plan.id,
                plan_title=plan.title,
            )

    def _notify_plan(
        self,
        *,
        action: str,
        trainer_id: str,
        trainer_user_id: str,
        trainee: models.TraineeProfile,
        plan_id: str,
        plan_title: str,
    ) -> None:
        trainer_name = "Your trainer"
        user = self.users.get(trainer_user_id) if trainer_user_id else None
        if user is not None:
            trainer_name = user.name
        try:
            self.push.notify_plan_assignment_changed_sync(
                action=action,
                peer_trainee_user_id=trainee.user_id,
                actor_trainer_user_id=trainer_user_id or None,
                plan_id=plan_id,
                plan_title=plan_title,
                trainer_user_id=trainer_user_id,
                trainee_user_id=trainee.user_id,
                trainee_profile_id=trainee.id,
                trainer_name=trainer_name,
            )
        except Exception:
            log.exception(
                "plan_assignment_notify_failed",
                action=action,
                plan_id=plan_id,
                trainee_id=trainee.id,
                trainer_id=trainer_id,
            )

    def trainee_meals(self, trainer_id: str, trainee_id: str, on_date) -> list[MealOut]:
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [meal_out(meal) for meal in self.meals.list_for_trainee(trainee_id, on=on_date)]

    def trainee_macros(self, trainer_id: str, trainee_id: str, on_date):
        meals = self.trainee_meals(trainer_id, trainee_id, on_date)
        return _sum_macros(meals)

    def trainee_logs(self, trainer_id: str, trainee_id: str):
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        return [workout_log_out(log) for log in self.logs.list_for_trainee(trainee_id)]

    def trainee_analytics(
        self, trainer_id: str, trainee_id: str, *, period_days: int = 30
    ) -> TraineeAnalyticsOut:
        """Aggregate workout history for trainer Analytics / History UI."""
        require_owned_trainee(self.trainees, trainer_id, trainee_id)
        period_days = max(1, min(int(period_days or 30), 90))
        logs = self.logs.list_for_trainee(trainee_id)
        cutoff = _utc_now() - timedelta(days=period_days)

        def _aware(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        in_period = [log for log in logs if _aware(log.completed_at) >= cutoff]
        by_day: dict[str, TraineeAnalyticsDay] = {}
        exercise_stats: dict[str, TraineeExerciseStat] = {}
        total_duration = 0
        total_volume = 0.0

        for log in in_period:
            day_key = _aware(log.completed_at).date().isoformat()
            bucket = by_day.get(day_key) or TraineeAnalyticsDay(date=day_key)
            session_volume = 0.0
            for s in log.sets or []:
                vol = float(s.reps or 0) * float(s.weight_kg or 0)
                session_volume += vol
                ex = exercise_stats.get(s.exercise_id) or TraineeExerciseStat(exercise_id=s.exercise_id)
                ex.sets += 1
                ex.reps += int(s.reps or 0)
                ex.volume_kg += vol
                exercise_stats[s.exercise_id] = ex
            bucket.sessions += 1
            bucket.duration_minutes += int(log.duration_minutes or 0)
            bucket.volume_kg += session_volume
            by_day[day_key] = bucket
            total_duration += int(log.duration_minutes or 0)
            total_volume += session_volume

        top = sorted(exercise_stats.values(), key=lambda x: x.volume_kg, reverse=True)[:5]
        days = sorted(by_day.values(), key=lambda d: d.date)
        last_at = _aware(logs[0].completed_at) if logs else None
        return TraineeAnalyticsOut(
            trainee_id=trainee_id,
            period_days=period_days,
            sessions_completed=len(in_period),
            total_duration_minutes=total_duration,
            total_volume_kg=round(total_volume, 1),
            last_workout_at=last_at,
            workouts_by_day=days,
            top_exercises=top,
            recent_logs=[workout_log_out(log) for log in logs[:10]],
        )

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
