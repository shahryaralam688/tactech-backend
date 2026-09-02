from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    trainer: Mapped["TrainerProfile | None"] = relationship(back_populates="user", uselist=False)
    trainee: Mapped["TraineeProfile | None"] = relationship(back_populates="user", uselist=False)


class TrainerProfile(Base):
    __tablename__ = "trainer_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    invite_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    specialty: Mapped[str] = mapped_column(String(255), nullable=False)
    years_experience: Mapped[int] = mapped_column(Integer, nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="trainer")
    trainees: Mapped[list["TraineeProfile"]] = relationship(back_populates="trainer")
    plans: Mapped[list["WorkoutPlan"]] = relationship(back_populates="trainer")


class TraineeProfile(Base):
    __tablename__ = "trainee_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    trainer_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    goal: Mapped[str] = mapped_column(String(255), nullable=False)
    height_cm: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    daily_calorie_target: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped[User] = relationship(back_populates="trainee")
    trainer: Mapped[TrainerProfile | None] = relationship(back_populates="trainees")
    assignment: Mapped["PlanAssignment | None"] = relationship(
        back_populates="trainee",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    muscle_group: Mapped[str] = mapped_column(String(64), nullable=False)
    equipment: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), nullable=False)
    cues: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    icon: Mapped[str] = mapped_column(String(128), nullable=False)


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainer_profiles.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    focus: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    trainer: Mapped[TrainerProfile] = relationship(back_populates="plans")
    exercises: Mapped[list["WorkoutExercise"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.sort_order",
    )
    days: Mapped[list["PlanDay"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanDay.sort_order",
    )
    assignments: Mapped[list["PlanAssignment"]] = relationship(back_populates="plan")


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    sets: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    plan: Mapped[WorkoutPlan] = relationship(back_populates="exercises")
    exercise: Mapped[Exercise] = relationship()


class PlanDay(Base):
    __tablename__ = "plan_days"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[str] = mapped_column(String(16), nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    focus: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warmup: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    plan: Mapped[WorkoutPlan] = relationship(back_populates="days")
    exercises: Mapped[list["PlanExercise"]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="PlanExercise.sort_order",
    )


class PlanExercise(Base):
    __tablename__ = "plan_exercises"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_day_id: Mapped[str] = mapped_column(ForeignKey("plan_days.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sets: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    side: Mapped[str | None] = mapped_column(String(32), nullable=True)

    day: Mapped[PlanDay] = relationship(back_populates="exercises")
    prescribed_sets: Mapped[list["PlanPrescribedSet"]] = relationship(
        back_populates="plan_exercise",
        cascade="all, delete-orphan",
        order_by="PlanPrescribedSet.set_number",
    )


class PlanPrescribedSet(Base):
    __tablename__ = "plan_prescribed_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_exercise_id: Mapped[str] = mapped_column(ForeignKey("plan_exercises.id", ondelete="CASCADE"), index=True)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)

    plan_exercise: Mapped[PlanExercise] = relationship(back_populates="prescribed_sets")


class PlanAssignment(Base):
    __tablename__ = "plan_assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"), index=True)
    trainee_id: Mapped[str] = mapped_column(
        ForeignKey("trainee_profiles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plan: Mapped[WorkoutPlan] = relationship(back_populates="assignments")
    trainee: Mapped[TraineeProfile] = relationship(back_populates="assignment")


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainee_id: Mapped[str] = mapped_column(ForeignKey("trainee_profiles.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    sets: Mapped[list["WorkoutSetLog"]] = relationship(
        back_populates="log",
        cascade="all, delete-orphan",
        order_by="WorkoutSetLog.set_number",
    )


class WorkoutSetLog(Base):
    __tablename__ = "workout_set_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workout_log_id: Mapped[str] = mapped_column(ForeignKey("workout_logs.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)

    log: Mapped[WorkoutLog] = relationship(back_populates="sets")


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainee_id: Mapped[str] = mapped_column(ForeignKey("trainee_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    portion_grams: Mapped[float] = mapped_column(Float, nullable=False)
    calories: Mapped[int] = mapped_column(Integer, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    fat: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TrainerFeedback(Base):
    __tablename__ = "trainer_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainer_profiles.id", ondelete="CASCADE"), index=True)
    trainee_id: Mapped[str] = mapped_column(ForeignKey("trainee_profiles.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    related_exercise_id: Mapped[str | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="SET NULL"),
        nullable=True,
    )


class FormReport(Base):
    __tablename__ = "form_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainee_id: Mapped[str] = mapped_column(ForeignKey("trainee_profiles.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    cues: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rep_count: Mapped[int] = mapped_column(Integer, nullable=False)


class FoodKnowledge(Base):
    __tablename__ = "food_knowledge"
    __table_args__ = (UniqueConstraint("name", name="uq_food_knowledge_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    calories: Mapped[int] = mapped_column(Integer, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    fat: Mapped[float] = mapped_column(Float, nullable=False)
