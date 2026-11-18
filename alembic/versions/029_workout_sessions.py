"""Add workout_sessions and workout_session_sets for in-progress tracking.

Revision ID: 029_workout_sessions
Revises: 028_plan_source
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_workout_sessions"
down_revision: Union[str, None] = "028_plan_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("trainee_id", sa.String(64), sa.ForeignKey("trainee_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("workout_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_day_id", sa.String(64), sa.ForeignKey("plan_days.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workout_log_id", sa.String(64), sa.ForeignKey("workout_logs.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_workout_sessions_trainee_status", "workout_sessions", ["trainee_id", "status"])

    op.create_table(
        "workout_session_sets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("exercise_id", sa.String(64), sa.ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("set_number", sa.Integer, nullable=False),
        sa.Column("reps", sa.Integer, nullable=False),
        sa.Column("weight_kg", sa.Float, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "exercise_id", "set_number", name="uq_session_exercise_set"),
    )


def downgrade() -> None:
    op.drop_table("workout_session_sets")
    op.drop_table("workout_sessions")
