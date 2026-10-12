"""Coach discovery profiles + entitlements (Phase 1)

Revision ID: 014_coach_discovery
Revises: 013_chat_wa
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_coach_discovery"
down_revision: Union[str, None] = "013_chat_wa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("headline", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="PK"),
        sa.Column(
            "specialties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "languages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("gym_name", sa.String(length=255), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cover_image_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coach_profiles_trainer_id", "coach_profiles", ["trainer_id"])
    op.create_index("ix_coach_profiles_user_id", "coach_profiles", ["user_id"])
    op.create_index(
        "ix_coach_profiles_public_updated",
        "coach_profiles",
        ["is_public", "updated_at"],
    )

    op.create_table(
        "ai_entitlements",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("plan", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="inactive"),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "coach_boosts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("tier", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="inactive"),
        sa.Column("payment_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("payment_events")
    op.drop_table("coach_boosts")
    op.drop_table("ai_entitlements")
    op.drop_index("ix_coach_profiles_public_updated", table_name="coach_profiles")
    op.drop_index("ix_coach_profiles_user_id", table_name="coach_profiles")
    op.drop_index("ix_coach_profiles_trainer_id", table_name="coach_profiles")
    op.drop_table("coach_profiles")
