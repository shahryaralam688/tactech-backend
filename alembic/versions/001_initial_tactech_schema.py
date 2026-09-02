"""initial tactech schema

Revision ID: 001_initial
Revises:
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)

    op.create_table(
        "trainer_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("invite_code", sa.String(length=32), nullable=False),
        sa.Column("specialty", sa.String(length=255), nullable=False),
        sa.Column("years_experience", sa.Integer(), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_trainer_profiles_invite_code", "trainer_profiles", ["invite_code"], unique=True)

    op.create_table(
        "exercises",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("muscle_group", sa.String(length=64), nullable=False),
        sa.Column("equipment", sa.String(length=64), nullable=False),
        sa.Column("difficulty", sa.String(length=32), nullable=False),
        sa.Column("cues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("icon", sa.String(length=128), nullable=False),
    )

    op.create_table(
        "trainee_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("trainer_id", sa.String(length=64), nullable=True),
        sa.Column("goal", sa.String(length=255), nullable=False),
        sa.Column("height_cm", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("daily_calorie_target", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_trainee_profiles_trainer_id", "trainee_profiles", ["trainer_id"], unique=False)

    op.create_table(
        "workout_plans",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainer_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("focus", sa.String(length=255), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workout_plans_trainer_id", "workout_plans", ["trainer_id"], unique=False)

    op.create_table(
        "workout_exercises",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("recommended_weight_kg", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["workout_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_workout_exercises_plan_id", "workout_exercises", ["plan_id"], unique=False)

    op.create_table(
        "plan_assignments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["workout_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trainee_id"),
    )
    op.create_index("ix_plan_assignments_plan_id", "plan_assignments", ["plan_id"], unique=False)

    op.create_table(
        "workout_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["workout_plans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workout_logs_trainee_id", "workout_logs", ["trainee_id"], unique=False)
    op.create_index("ix_workout_logs_plan_id", "workout_logs", ["plan_id"], unique=False)

    op.create_table(
        "workout_set_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("workout_log_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["workout_log_id"], ["workout_logs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_workout_set_logs_workout_log_id", "workout_set_logs", ["workout_log_id"], unique=False)

    op.create_table(
        "meals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portion_grams", sa.Float(), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("carbs", sa.Float(), nullable=False),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_estimate", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_meals_trainee_id", "meals", ["trainee_id"], unique=False)
    op.create_index("ix_meals_eaten_at", "meals", ["eaten_at"], unique=False)

    op.create_table(
        "trainer_feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainer_id", sa.String(length=64), nullable=False),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("related_exercise_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_exercise_id"], ["exercises.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_trainer_feedback_trainer_id", "trainer_feedback", ["trainer_id"], unique=False)
    op.create_index("ix_trainer_feedback_trainee_id", "trainer_feedback", ["trainee_id"], unique=False)

    op.create_table(
        "form_reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("cues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rep_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_form_reports_trainee_id", "form_reports", ["trainee_id"], unique=False)

    op.create_table(
        "food_knowledge",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("carbs", sa.Float(), nullable=False),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.UniqueConstraint("name", name="uq_food_knowledge_name"),
    )


def downgrade() -> None:
    op.drop_table("food_knowledge")
    op.drop_table("form_reports")
    op.drop_table("trainer_feedback")
    op.drop_table("meals")
    op.drop_table("workout_set_logs")
    op.drop_table("workout_logs")
    op.drop_table("plan_assignments")
    op.drop_table("workout_exercises")
    op.drop_table("workout_plans")
    op.drop_table("trainee_profiles")
    op.drop_table("exercises")
    op.drop_table("trainer_profiles")
    op.drop_table("users")
