"""Phase 5: coach reviews, reports, rating aggregates

Revision ID: 018_coach_reviews
Revises: 017_local_boost
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_coach_reviews"
down_revision: Union[str, None] = "017_local_boost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coach_profiles",
        sa.Column("rating_avg", sa.Numeric(3, 2), nullable=True),
    )
    op.add_column(
        "coach_profiles",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "coach_reviews",
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
            "author_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_trainee_id",
            sa.String(length=64),
            sa.ForeignKey("trainee_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stars >= 1 AND stars <= 5", name="ck_coach_reviews_stars"),
        sa.UniqueConstraint(
            "author_user_id",
            "coach_profile_id",
            name="uq_coach_reviews_author_coach",
        ),
    )
    op.create_index("ix_coach_reviews_author_user_id", "coach_reviews", ["author_user_id"])
    op.create_index(
        "ix_coach_reviews_coach_created",
        "coach_reviews",
        ["coach_profile_id", "created_at"],
        postgresql_where=sa.text("is_hidden = false"),
    )

    op.create_table(
        "coach_review_reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(length=64),
            sa.ForeignKey("coach_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "review_id",
            "reporter_user_id",
            name="uq_coach_review_reports_review_reporter",
        ),
    )
    op.create_index("ix_coach_review_reports_review_id", "coach_review_reports", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_coach_review_reports_review_id", table_name="coach_review_reports")
    op.drop_table("coach_review_reports")
    op.drop_index("ix_coach_reviews_coach_created", table_name="coach_reviews")
    op.drop_index("ix_coach_reviews_author_user_id", table_name="coach_reviews")
    op.drop_table("coach_reviews")
    op.drop_column("coach_profiles", "rating_count")
    op.drop_column("coach_profiles", "rating_avg")
