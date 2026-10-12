"""Phase 6: coach profile analytics events

Revision ID: 019_coach_analytics
Revises: 018_coach_reviews
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_coach_analytics"
down_revision: Union[str, None] = "018_coach_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_profile_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "coach_profile_id",
            sa.String(length=64),
            sa.ForeignKey("coach_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_id",
            sa.String(length=64),
            sa.ForeignKey("trainer_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "viewer_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_coach_events_profile_type_created",
        "coach_profile_events",
        ["coach_profile_id", "event_type", "created_at"],
    )
    op.create_index(
        "ix_coach_events_profile_viewer_type_created",
        "coach_profile_events",
        ["coach_profile_id", "viewer_user_id", "event_type", "created_at"],
    )
    op.create_index("ix_coach_events_trainer_id", "coach_profile_events", ["trainer_id"])


def downgrade() -> None:
    op.drop_index("ix_coach_events_trainer_id", table_name="coach_profile_events")
    op.drop_index(
        "ix_coach_events_profile_viewer_type_created", table_name="coach_profile_events"
    )
    op.drop_index("ix_coach_events_profile_type_created", table_name="coach_profile_events")
    op.drop_table("coach_profile_events")
