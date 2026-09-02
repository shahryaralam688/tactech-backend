"""fitness assessments and nullable plan trainer

Revision ID: 003_assessments
Revises: 002_weekly_plan
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_assessments"
down_revision: Union[str, None] = "002_weekly_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "workout_plans",
        "trainer_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.drop_constraint("workout_plans_trainer_id_fkey", "workout_plans", type_="foreignkey")
    op.create_foreign_key(
        "workout_plans_trainer_id_fkey",
        "workout_plans",
        "trainer_profiles",
        ["trainer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "fitness_assessments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("trainer_id", sa.String(length=64), nullable=True),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["trainee_id"], ["trainee_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_id"], ["workout_plans.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_fitness_assessments_trainee_id", "fitness_assessments", ["trainee_id"])
    op.create_index("ix_fitness_assessments_trainer_id", "fitness_assessments", ["trainer_id"])


def downgrade() -> None:
    op.drop_table("fitness_assessments")
    op.drop_constraint("workout_plans_trainer_id_fkey", "workout_plans", type_="foreignkey")
    op.create_foreign_key(
        "workout_plans_trainer_id_fkey",
        "workout_plans",
        "trainer_profiles",
        ["trainer_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column(
        "workout_plans",
        "trainer_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
