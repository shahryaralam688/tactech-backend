"""Add workout_plans.source + owner_trainee_id for AI vs trainer lock.

Revision ID: 028_plan_source
Revises: 027_ai_gateway_usage
Create Date: 2026-10-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028_plan_source"
down_revision: Union[str, None] = "027_ai_gateway_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workout_plans",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="trainer"),
    )
    op.add_column(
        "workout_plans",
        sa.Column("owner_trainee_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_workout_plans_source", "workout_plans", ["source"])
    op.create_index("ix_workout_plans_owner_trainee_id", "workout_plans", ["owner_trainee_id"])
    op.create_foreign_key(
        "fk_workout_plans_owner_trainee_id",
        "workout_plans",
        "trainee_profiles",
        ["owner_trainee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Backfill: no trainer → ai; else trainer
    op.execute(
        """
        UPDATE workout_plans
        SET source = CASE
            WHEN trainer_id IS NULL OR trainer_id = '' THEN 'ai'
            ELSE 'trainer'
        END
        """
    )
    # Owner for AI plans from current assignment when present
    op.execute(
        """
        UPDATE workout_plans wp
        SET owner_trainee_id = pa.trainee_id
        FROM plan_assignments pa
        WHERE pa.plan_id = wp.id
          AND wp.source = 'ai'
          AND wp.owner_trainee_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_workout_plans_owner_trainee_id", "workout_plans", type_="foreignkey")
    op.drop_index("ix_workout_plans_owner_trainee_id", table_name="workout_plans")
    op.drop_index("ix_workout_plans_source", table_name="workout_plans")
    op.drop_column("workout_plans", "owner_trainee_id")
    op.drop_column("workout_plans", "source")
