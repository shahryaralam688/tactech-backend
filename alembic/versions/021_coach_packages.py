"""Phase 8: coach service packages + inquire

Revision ID: 021_coach_packages
Revises: 020_coach_verification
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_coach_packages"
down_revision: Union[str, None] = "020_coach_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_packages",
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
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("billing_period", sa.String(length=32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column(
            "includes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("delivery", sa.String(length=32), nullable=False, server_default="online"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_coach_packages_amount_minor"),
    )
    op.create_index(
        "ix_coach_packages_profile_status_sort",
        "coach_packages",
        ["coach_profile_id", "status", "sort_order"],
    )
    op.create_index("ix_coach_packages_user_id", "coach_packages", ["user_id"])
    op.create_index(
        "uq_coach_packages_one_featured",
        "coach_packages",
        ["coach_profile_id"],
        unique=True,
        postgresql_where=sa.text("is_featured = true AND status = 'active'"),
    )

    op.create_table(
        "coach_package_inquiries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "package_id",
            sa.String(length=64),
            sa.ForeignKey("coach_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "coach_profile_id",
            sa.String(length=64),
            sa.ForeignKey("coach_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainee_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_package_inquiries_package_created",
        "coach_package_inquiries",
        ["package_id", "created_at"],
    )
    op.create_index(
        "ix_package_inquiries_coach_created",
        "coach_package_inquiries",
        ["coach_profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_package_inquiries_coach_created", table_name="coach_package_inquiries")
    op.drop_index("ix_package_inquiries_package_created", table_name="coach_package_inquiries")
    op.drop_table("coach_package_inquiries")
    op.drop_index("uq_coach_packages_one_featured", table_name="coach_packages")
    op.drop_index("ix_coach_packages_user_id", table_name="coach_packages")
    op.drop_index("ix_coach_packages_profile_status_sort", table_name="coach_packages")
    op.drop_table("coach_packages")
