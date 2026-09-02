from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.repositories.assignment import AssignmentRepository
from app.repositories.exercise import ExerciseRepository
from app.repositories.plan import PlanRepository
from app.repositories.trainee import TraineeRepository
from app.repositories.user import UserRepository
from app.schemas.assessment import AssessmentProgramOut, AssessmentRequest
from app.services.programming_engine import generate_program


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")
    return "ex-ai-" + "-".join(part for part in cleaned.split("-") if part)[:8]


class AssessmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.trainees = TraineeRepository(db)
        self.users = UserRepository(db)
        self.exercises = ExerciseRepository(db)
        self.plans = PlanRepository(db)
        self.assignments = AssignmentRepository(db)

    def submit(self, trainee_id: str, payload: AssessmentRequest) -> AssessmentProgramOut:
        trainee = self.trainees.get(trainee_id)
        if trainee is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError("Trainee profile not found.")
        user = self.users.get(trainee.user_id)
        user_name = user.name if user else "Trainee"

        result = generate_program(payload, user_name)
        plan = self._persist_plan(trainee, result["plan"])
        assignment = models.PlanAssignment(
            id=str(uuid4()),
            plan_id=plan.id,
            trainee_id=trainee.id,
            assigned_at=_utc_now(),
        )
        self.assignments.replace(assignment)

        trainee.goal = payload.goal
        trainee.weight_kg = payload.weight_kg
        trainee.daily_calorie_target = result["traineeUpdate"]["dailyCalorieTarget"]

        assessment = models.FitnessAssessment(
            id=str(uuid4()),
            trainee_id=trainee.id,
            trainer_id=trainee.trainer_id,
            plan_id=plan.id,
            created_at=_utc_now(),
            payload=payload.model_dump(by_alias=True),
            result=result,
        )
        self.db.add(assessment)

        if trainee.trainer_id:
            self.db.add(
                models.TrainerFeedback(
                    id=str(uuid4()),
                    trainer_id=trainee.trainer_id,
                    trainee_id=trainee.id,
                    message=f"TacTech AI assessment for {user_name}: {result['coachSummary']}",
                    created_at=_utc_now(),
                    related_exercise_id=None,
                )
            )

        self.db.flush()
        return AssessmentProgramOut.model_validate(result)

    def latest_for_trainee(self, trainee_id: str) -> AssessmentProgramOut | None:
        stmt = (
            select(models.FitnessAssessment)
            .where(models.FitnessAssessment.trainee_id == trainee_id)
            .order_by(models.FitnessAssessment.created_at.desc())
        )
        row = self.db.execute(stmt).scalars().first()
        if row is None:
            return None
        return AssessmentProgramOut.model_validate(row.result)

    def latest_for_trainer(self, trainer_id: str, trainee_id: str) -> AssessmentProgramOut | None:
        trainee = self.trainees.get(trainee_id)
        if trainee is None or trainee.trainer_id != trainer_id:
            from app.core.exceptions import ForbiddenError

            if trainee is None:
                from app.core.exceptions import NotFoundError

                raise NotFoundError("Trainee not found.")
            raise ForbiddenError("This trainee is not on your roster.")
        return self.latest_for_trainee(trainee_id)

    def _persist_plan(self, trainee: models.TraineeProfile, plan_data: dict) -> models.WorkoutPlan:
        days = []
        flat = []
        for day_index, day in enumerate(plan_data["days"]):
            day_exercises = []
            for ex_index, item in enumerate(day["exercises"]):
                exercise = self._resolve_exercise(item)
                day_exercises.append(
                    models.PlanExercise(
                        id=str(uuid4()),
                        exercise_id=exercise.id,
                        sort_order=ex_index,
                        sets=item["sets"],
                        reps=item["reps"],
                        rest_seconds=item["restSeconds"],
                        recommended_weight_kg=item.get("recommendedWeightKg"),
                        tempo=item.get("tempo"),
                        rpe=item.get("rpe"),
                        notes=item.get("notes"),
                        side=None,
                        prescribed_sets=[
                            models.PlanPrescribedSet(
                                id=str(uuid4()),
                                set_number=row["setNumber"],
                                reps=row["reps"],
                                weight_kg=row.get("weightKg"),
                                rpe=row.get("rpe"),
                            )
                            for row in item.get("prescribedSets", [])
                        ],
                    )
                )
                flat.append(
                    models.WorkoutExercise(
                        id=str(uuid4()),
                        exercise_id=exercise.id,
                        sets=item["sets"],
                        reps=item["reps"],
                        rest_seconds=item["restSeconds"],
                        recommended_weight_kg=item.get("recommendedWeightKg"),
                        sort_order=len(flat),
                    )
                )
            days.append(
                models.PlanDay(
                    id=str(uuid4()),
                    weekday=day["weekday"],
                    start_time=day.get("startTime"),
                    title=day["title"],
                    focus=day["focus"],
                    duration_minutes=day["durationMinutes"],
                    location=day.get("location"),
                    warmup=day.get("warmup"),
                    cooldown=day.get("cooldown"),
                    coach_notes=day.get("coachNotes"),
                    sort_order=day_index,
                    exercises=day_exercises,
                )
            )

        plan = models.WorkoutPlan(
            id=str(uuid4()),
            trainer_id=trainee.trainer_id,
            title=plan_data["title"],
            focus=plan_data["focus"],
            duration_minutes=plan_data["durationMinutes"],
            level=plan_data["level"],
            days_per_week=plan_data["daysPerWeek"],
            notes=plan_data.get("notes"),
            exercises=flat,
            days=days,
        )
        self.plans.add(plan)
        return plan

    def _resolve_exercise(self, item: dict) -> models.Exercise:
        name = item["exerciseName"]
        existing = self.exercises.get_by_name(name)
        if existing:
            return existing
        exercise = models.Exercise(
            id=_slug(name)[:64],
            name=name,
            muscle_group=item.get("muscleGroup") or "Full Body",
            equipment=item.get("equipment") or "Bodyweight",
            difficulty=item.get("difficulty") or "Beginner",
            cues=item.get("cues") or [],
            icon="figure.strengthtraining.traditional",
        )
        if self.exercises.get(exercise.id):
            exercise.id = f"{exercise.id}-{uuid4().hex[:6]}"
        return self.exercises.add(exercise)
