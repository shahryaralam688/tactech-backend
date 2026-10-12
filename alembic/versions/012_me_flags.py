"""User assessment/onboarding completion flags

Revision ID: 012_me_flags
Revises: 011_notif
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_me_flags"
down_revision: Union[str, None] = "011_notif"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("assessment_completed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Backfill from existing assessment history
    op.execute(
        """
        UPDATE users u
        SET assessment_completed = true
        WHERE u.role = 'trainee'
          AND EXISTS (
            SELECT 1 FROM trainee_profiles tp
            JOIN fitness_assessments fa ON fa.trainee_id = tp.id
            WHERE tp.user_id = u.id
          )
        """
    )
    op.execute(
        """
        UPDATE users u
        SET assessment_completed = true
        WHERE u.role = 'trainer'
          AND EXISTS (
            SELECT 1 FROM trainer_profiles tp
            JOIN trainer_assessments ta ON ta.trainer_id = tp.id
            WHERE tp.user_id = u.id
          )
        """
    )
    # Onboarding: assessment implies onboarding; also profile essentials
    op.execute(
        """
        UPDATE users
        SET onboarding_completed = true
        WHERE assessment_completed = true
        """
    )
    op.execute(
        """
        UPDATE users u
        SET onboarding_completed = true
        WHERE u.role = 'trainee'
          AND EXISTS (
            SELECT 1 FROM trainee_profiles tp
            WHERE tp.user_id = u.id
              AND length(trim(tp.goal)) > 0
              AND tp.height_cm > 0
              AND tp.weight_kg > 0
          )
          AND length(trim(u.name)) > 0
        """
    )
    op.execute(
        """
        UPDATE users u
        SET onboarding_completed = true
        WHERE u.role = 'trainer'
          AND EXISTS (
            SELECT 1 FROM trainer_profiles tp
            WHERE tp.user_id = u.id
              AND length(trim(tp.specialty)) > 0
              AND length(trim(tp.bio)) > 0
          )
          AND length(trim(u.name)) > 0
        """
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed")
    op.drop_column("users", "assessment_completed")
