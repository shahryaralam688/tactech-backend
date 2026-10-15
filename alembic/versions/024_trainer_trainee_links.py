"""Trainer ↔ trainee invite roster links (soft-end history).

Revision ID: 024_trainer_trainee_links
Revises: 023_exercise_form3d
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_trainer_trainee_links"
down_revision: Union[str, None] = "023_exercise_form3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trainer_trainee_links",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainee_id",
            sa.String(length=64),
            sa.ForeignKey("trainee_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainee_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("invite_code_used", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="invite"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_user_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_ttl_trainee_status",
        "trainer_trainee_links",
        ["trainee_id", "status"],
    )
    op.create_index(
        "ix_ttl_trainer_status",
        "trainer_trainee_links",
        ["trainer_id", "status"],
    )
    # At most one active link per trainee
    op.create_index(
        "uq_ttl_trainee_active",
        "trainer_trainee_links",
        ["trainee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # Backfill from existing trainee_profiles.trainer_id
    op.execute(
        """
        INSERT INTO trainer_trainee_links (
            id, trainer_id, trainee_id, trainer_user_id, trainee_user_id,
            status, invite_code_used, source, created_at, ended_at, ended_by_user_id
        )
        SELECT
            'ttl-mig-' || tp.id,
            tp.trainer_id,
            tp.id,
            tr.user_id,
            tp.user_id,
            'active',
            tr.invite_code,
            'migrate',
            NOW(),
            NULL,
            NULL
        FROM trainee_profiles tp
        JOIN trainer_profiles tr ON tr.id = tp.trainer_id
        WHERE tp.trainer_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trainer_trainee_links l
            WHERE l.trainee_id = tp.id AND l.status = 'active'
          )
        """
    )


def downgrade() -> None:
    op.drop_index("uq_ttl_trainee_active", table_name="trainer_trainee_links")
    op.drop_index("ix_ttl_trainer_status", table_name="trainer_trainee_links")
    op.drop_index("ix_ttl_trainee_status", table_name="trainer_trainee_links")
    op.drop_table("trainer_trainee_links")
