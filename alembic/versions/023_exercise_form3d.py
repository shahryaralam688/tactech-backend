"""Exercise catalog Form Studio 3D metadata (additive).

Revision ID: 023_exercise_form3d
Revises: 022_coach_follows
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_exercise_form3d"
down_revision: Union[str, None] = "022_coach_follows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("exercises", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column(
        "exercises",
        sa.Column("muscles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("exercises", sa.Column("level", sa.String(length=32), nullable=True))
    op.add_column(
        "exercises",
        sa.Column("equipment_list", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("exercises", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column(
        "exercises",
        sa.Column("common_mistakes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("exercises", sa.Column("thumbnail_url", sa.String(length=512), nullable=True))
    op.add_column(
        "exercises",
        sa.Column(
            "form3d_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("exercises", sa.Column("form3d_clip_id", sa.String(length=128), nullable=True))
    op.add_column("exercises", sa.Column("form3d_character", sa.String(length=64), nullable=True))
    op.add_column(
        "exercises", sa.Column("form3d_animation_url", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "exercises",
        sa.Column("form3d_guide", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "exercises",
        sa.Column("form3d_cues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("exercises", sa.Column("mixamo_query", sa.String(length=255), nullable=True))
    op.add_column(
        "exercises",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "exercises",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "exercises",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_exercises_active_sort", "exercises", ["active", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_exercises_active_sort", table_name="exercises")
    for col in (
        "updated_at",
        "active",
        "sort_order",
        "mixamo_query",
        "form3d_cues",
        "form3d_guide",
        "form3d_animation_url",
        "form3d_character",
        "form3d_clip_id",
        "form3d_enabled",
        "thumbnail_url",
        "common_mistakes",
        "instructions",
        "equipment_list",
        "level",
        "muscles",
        "category",
    ):
        op.drop_column("exercises", col)
