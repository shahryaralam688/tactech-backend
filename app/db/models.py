from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base

# OpenAI text-embedding-3-small
COACH_EMBEDDING_DIM = 1536


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="Regular")
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    avatar_asset: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class JoinRequest(Base):
    """Invite-code join request: pending until trainer accept/reject or trainee cancel."""

    __tablename__ = "join_requests"
    __table_args__ = (
        Index("ix_join_requests_trainer_status", "trainer_user_id", "status"),
        Index("ix_join_requests_trainee_status", "trainee_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trainer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trainee_id: Mapped[str] = mapped_column(
        ForeignKey("trainee_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invite_code: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(String(280), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # pending|accepted|rejected|cancelled
    reject_reason: Mapped[str | None] = mapped_column(String(280), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrainerTraineeLink(Base):
    """Invite (or follow) roster relationship with soft-end history.

    Active roster pointer remains ``TraineeProfile.trainer_id`` for fast queries;
    this table is the durable lifecycle (active|ended) and re-link history.
    """

    __tablename__ = "trainer_trainee_links"
    __table_args__ = (
        Index("ix_ttl_trainee_status", "trainee_id", "status"),
        Index("ix_ttl_trainer_status", "trainer_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainee_id: Mapped[str] = mapped_column(
        ForeignKey("trainee_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # active | ended
    invite_code_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="invite")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Exercise(Base):
    """Curated plan catalog. Optional Form Studio 3D demo metadata (Mixamo X_Bot)."""

    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    muscle_group: Mapped[str] = mapped_column(String(64), nullable=False)
    equipment: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), nullable=False)
    cues: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    icon: Mapped[str] = mapped_column(String(128), nullable=False)
    # Enriched catalog + Form Studio 3D (additive; legacy columns unchanged)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    muscles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    equipment_list: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_mistakes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    form3d_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    form3d_clip_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    form3d_character: Mapped[str | None] = mapped_column(String(64), nullable=True)
    form3d_animation_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    form3d_guide: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    form3d_cues: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mixamo_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ai = solo LLM generate; trainer = human coach program
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="trainer", index=True)
    owner_trainee_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainee_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    focus: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trainer: Mapped[TrainerProfile | None] = relationship(back_populates="plans")
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


class FitnessAssessment(Base):
    __tablename__ = "fitness_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainee_id: Mapped[str] = mapped_column(ForeignKey("trainee_profiles.id", ondelete="CASCADE"), index=True)
    trainer_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("workout_plans.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)


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


class ExerciseTemplate(Base):
    __tablename__ = "exercise_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainer_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sets: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    how_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    side: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    set_rows: Mapped[list["ExerciseTemplateSetRow"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ExerciseTemplateSetRow.set_number",
    )


class ExerciseTemplateSetRow(Base):
    __tablename__ = "exercise_template_set_rows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("exercise_templates.id", ondelete="CASCADE"),
        index=True,
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    template: Mapped[ExerciseTemplate] = relationship(back_populates="set_rows")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    notifications: Mapped[dict] = mapped_column(JSONB, nullable=False)
    security: Mapped[dict] = mapped_column(JSONB, nullable=False)
    language: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppFeedback(Base):
    __tablename__ = "app_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    areas: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportConversation(Base):
    __tablename__ = "support_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list["SupportMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("support_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    conversation: Mapped[SupportConversation] = relationship(back_populates="messages")


class TrainerAssessment(Base):
    __tablename__ = "trainer_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainer_profiles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CoachConversation(Base):
    __tablename__ = "coach_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="AI Coach")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list["CoachMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="CoachMessage.created_at",
    )


class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("coach_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False, default="text")  # text | voice | image
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    conversation: Mapped[CoachConversation] = relationship(back_populates="messages")


class CoachMemoryChunk(Base):
    __tablename__ = "coach_memory_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(COACH_EMBEDDING_DIM), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachRtcSession(Base):
    __tablename__ = "coach_rtc_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("coach_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatThread(Base):
    """1:1 trainer ↔ trainee human messaging (separate from AI coach + support)."""

    __tablename__ = "chat_threads"
    __table_args__ = (
        UniqueConstraint("trainer_user_id", "trainee_user_id", name="uq_chat_threads_pair"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trainee_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(280), nullable=True)
    trainer_unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trainee_unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "client_id", name="uq_chat_messages_client"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True)
    sender_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sender_role: Mapped[str] = mapped_column(String(16), nullable=False)  # trainer | trainee
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="text")  # text | attachment | call_event
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attachment_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # image | video | voice | file
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_outcome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_to_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reply_to_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reply_to_sender_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_for_everyone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    thread: Mapped[ChatThread] = relationship(back_populates="messages")
    reactions: Mapped[list["ChatMessageReaction"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class ChatMessageReaction(Base):
    """One emoji reaction per user per message (WhatsApp-like)."""

    __tablename__ = "chat_message_reactions"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_chat_reaction_user"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    message: Mapped[ChatMessage] = relationship(back_populates="reactions")


class ChatRtcSession(Base):
    """Peer-to-peer WebRTC session for trainer↔trainee video calls (not AI coach)."""

    __tablename__ = "chat_rtc_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | ended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DevicePushToken(Base):
    """APNs/FCM device tokens for remote push."""

    __tablename__ = "device_push_tokens"
    __table_args__ = (UniqueConstraint("user_id", "token", name="uq_device_push_tokens_user_token"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="ios")  # ios | android
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppNotification(Base):
    """In-app notification inbox (also drives remote push data payloads)."""

    __tablename__ = "app_notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachProfile(Base):
    """Public coach “file” for discovery (trainer-owned). Separate from TrainerProfile internals."""

    __tablename__ = "coach_profiles"
    __table_args__ = (
        Index("ix_coach_profiles_public_updated", "is_public", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    headline: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="PK")
    specialties: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    languages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    gym_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cover_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Phase 5 — denormalized aggregates (visible reviews only)
    rating_avg: Mapped[object | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Phase 7 — trust badge
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none"
    )  # none | pending | approved | rejected | revoked
    # Phase 9 — follow / hire
    follow_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual"
    )  # manual | auto_accept
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachFollow(Base):
    """Free marketplace follow/hire request → roster link on accept (Phase 9)."""

    __tablename__ = "coach_follows"
    __table_args__ = (
        Index("ix_coach_follows_trainer_status", "trainer_user_id", "status"),
        Index("ix_coach_follows_coach_status", "coach_profile_id", "status"),
        Index("ix_coach_follows_trainee_status", "trainee_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    trainer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    trainee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # pending | active | declined | ended
    package_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CoachPackage(Base):
    """Trainer service listing (Phase 8). Price is informational — no platform checkout yet."""

    __tablename__ = "coach_packages"
    __table_args__ = (
        Index("ix_coach_packages_profile_status_sort", "coach_profile_id", "status", "sort_order"),
        Index("ix_coach_packages_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    includes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    delivery: Mapped[str] = mapped_column(String(32), nullable=False, default="online")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachPackageInquiry(Base):
    """Package inquire → chat (Phase 8). Analytics-friendly; chat is source of conversation."""

    __tablename__ = "coach_package_inquiries"
    __table_args__ = (
        Index("ix_package_inquiries_package_created", "package_id", "created_at"),
        Index("ix_package_inquiries_coach_created", "coach_profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("coach_packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    trainee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachVerificationApplication(Base):
    """Trainer verification application (Phase 7). History kept; one open at a time."""

    __tablename__ = "coach_verification_applications"
    __table_args__ = (
        Index("ix_verify_apps_user_status", "user_id", "status"),
        Index("ix_verify_apps_status_submitted", "status", "submitted_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # draft | submitted | under_review | approved | rejected | canceled
    legal_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="PK")
    phone_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    attestation_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attestation_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachVerificationDocument(Base):
    """Evidence files for a verification application. Never expose on public discovery."""

    __tablename__ = "coach_verification_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("coach_verification_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # government_id | certification | selfie | other
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    original_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachProfileEvent(Base):
    """Privacy-safe discovery analytics (Phase 6). viewer_user_id never returned to trainers."""

    __tablename__ = "coach_profile_events"
    __table_args__ = (
        Index(
            "ix_coach_events_profile_type_created",
            "coach_profile_id",
            "event_type",
            "created_at",
        ),
        Index(
            "ix_coach_events_profile_viewer_type_created",
            "coach_profile_id",
            "viewer_user_id",
            "event_type",
            "created_at",
        ),
        Index("ix_coach_events_trainer_id", "trainer_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    viewer_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # view | impression | contact | contact_created
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CoachReview(Base):
    """Trainee review of a coach profile. One per (author_user_id, coach_profile_id)."""

    __tablename__ = "coach_reviews"
    __table_args__ = (
        UniqueConstraint("author_user_id", "coach_profile_id", name="uq_coach_reviews_author_coach"),
        Index("ix_coach_reviews_author_user_id", "author_user_id"),
        Index(
            "ix_coach_reviews_coach_created",
            "coach_profile_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coach_profile_id: Mapped[str] = mapped_column(
        ForeignKey("coach_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainer_id: Mapped[str] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_trainee_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainee_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoachReviewReport(Base):
    """Minimal moderation report. Auto-hide threshold: ≥3 distinct reporters."""

    __tablename__ = "coach_review_reports"
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "reporter_user_id",
            name="uq_coach_review_reports_review_reporter",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("coach_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiEntitlement(Base):
    """Trainee AI subscription (Apple IAP). One row per user; originalTransactionId unique globally."""

    __tablename__ = "ai_entitlements"
    __table_args__ = (
        Index("ix_ai_entitlements_user_status_ends", "user_id", "status", "ends_at"),
        Index("ix_ai_entitlements_ends_at", "ends_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan: Mapped[str | None] = mapped_column(String(64), nullable=True)  # product id alias
    apple_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    latest_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="expired"
    )  # active | grace | billing_retry | expired | refunded | revoked
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)  # Sandbox | Production
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # apple | manual
    raw_last_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingProduct(Base):
    """Sellable SKUs. type=boost (Stripe/JazzCash/Easypaisa) | ai (Apple IAP)."""

    __tablename__ = "billing_products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # boost | ai
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tier: Mapped[str] = mapped_column(String(64), nullable=False, default="featured")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    stripe_price_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    apple_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    billing_period: Mapped[str | None] = mapped_column(String(32), nullable=True)  # month | year
    providers: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # ["stripe"] | ["jazzcash","easypaisa"]
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiUsageWeekly(Base):
    """Free-tease AI message counters per ISO week (when AI_FREE_TEASE_MESSAGES_PER_WEEK > 0)."""

    __tablename__ = "ai_usage_weekly"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_ai_usage_weekly_user_week"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[object] = mapped_column(Date, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AiUsageDaily(Base):
    """Free daily AI chat counters (when AI_FREE_CHAT_DAILY_LIMIT > 0)."""

    __tablename__ = "ai_usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "usage_day", name="uq_ai_usage_daily_user_day"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    usage_day: Mapped[object] = mapped_column(Date, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AiPlanGenerationUsage(Base):
    """Lifetime free structured plan generation counter (AI_FREE_PLAN_GENERATIONS)."""

    __tablename__ = "ai_plan_generation_usage"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    generation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoachBoost(Base):
    """Discovery boost window. Active when status=active and startsAt <= now < endsAt.

    Stacking: extend endsAt from current endsAt when already active (single row).
    Idempotent activation keyed by stripe_checkout_session_id.
    """

    __tablename__ = "coach_boosts"
    __table_args__ = (
        Index("ix_coach_boosts_user_status_ends", "user_id", "status", "ends_at"),
        Index("ix_coach_boosts_ends_at", "ends_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trainer_id: Mapped[str | None] = mapped_column(
        ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | active | expired | refunded | canceled
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # stripe | jazzcash | easypaisa | manual
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merchant_txn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BoostCheckoutAttempt(Base):
    """One checkout attempt per redirect (Stripe session or JazzCash/Easypaisa txn)."""

    __tablename__ = "boost_checkout_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainer_profiles.id", ondelete="CASCADE"))
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # stripe | jazzcash | easypaisa
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="created"
    )  # created | redirected | paid | failed | expired
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    merchant_txn_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentEvent(Base):
    """Idempotent payment webhook ledger. Unique provider eventId."""

    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
