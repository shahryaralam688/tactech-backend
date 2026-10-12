"""Phase 9: coach follow / hire (free marketplace link)

Revision ID: 022_coach_follows
Revises: 021_coach_packages
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_coach_follows"
down_revision: Union[str, None] = "021_coach_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coach_profiles",
        sa.Column(
            "follow_mode",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
    )

    op.create_table(
        "coach_follows",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "coach_profile_id",
            sa.String(length=64),
            sa.ForeignKey("coach_profiles.id", ondelete="CASCADE"),
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
        sa.Column("package_id", sa.String(length=64), nullable=True),
        sa.Column("package_title", sa.String(length=80), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_user_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_coach_follows_trainer_status",
        "coach_follows",
        ["trainer_user_id", "status"],
    )
    op.create_index(
        "ix_coach_follows_coach_status",
        "coach_follows",
        ["coach_profile_id", "status"],
    )
    op.create_index(
        "ix_coach_follows_trainee_status",
        "coach_follows",
        ["trainee_user_id", "status"],
    )
    op.create_index(
        "uq_coach_follows_trainee_open",
        "coach_follows",
        ["trainee_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )


def downgrade() -> None:
    op.drop_index("uq_coach_follows_trainee_open", table_name="coach_follows")
    op.drop_index("ix_coach_follows_trainee_status", table_name="coach_follows")
    op.drop_index("ix_coach_follows_coach_status", table_name="coach_follows")
    op.drop_index("ix_coach_follows_trainer_status", table_name="coach_follows")
    op.drop_table("coach_follows")
    op.drop_column("coach_profiles", "follow_mode")
