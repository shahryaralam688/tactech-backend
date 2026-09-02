"""weekly plan days and prescribed sets

Revision ID: 002_weekly_plan
Revises: 001_initial
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_weekly_plan"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workout_plans", sa.Column("notes", sa.Text(), nullable=True))

    op.create_table(
        "plan_days",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("weekday", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.String(length=8), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("focus", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("warmup", sa.Text(), nullable=True),
        sa.Column("cooldown", sa.Text(), nullable=True),
        sa.Column("coach_notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["workout_plans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_plan_days_plan_id", "plan_days", ["plan_id"], unique=False)

    op.create_table(
        "plan_exercises",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_day_id", sa.String(length=64), nullable=False),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("recommended_weight_kg", sa.Float(), nullable=True),
        sa.Column("tempo", sa.String(length=32), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("side", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["plan_day_id"], ["plan_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_plan_exercises_plan_day_id", "plan_exercises", ["plan_day_id"], unique=False)

    op.create_table(
        "plan_prescribed_sets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_exercise_id", sa.String(length=64), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["plan_exercise_id"], ["plan_exercises.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_plan_prescribed_sets_plan_exercise_id",
        "plan_prescribed_sets",
        ["plan_exercise_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("plan_prescribed_sets")
    op.drop_table("plan_exercises")
    op.drop_table("plan_days")
    op.drop_column("workout_plans", "notes")
