"""Phase 7: coach verification applications + trust badge

Revision ID: 020_coach_verification
Revises: 019_coach_analytics
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_coach_verification"
down_revision: Union[str, None] = "019_coach_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coach_profiles",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "coach_profiles",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "coach_profiles",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
    )

    op.create_table(
        "coach_verification_applications",
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
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("legal_full_name", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="PK"),
        sa.Column("phone_last4", sa.String(length=4), nullable=True),
        sa.Column("attestation_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attestation_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("reviewer_user_id", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verify_apps_user_status",
        "coach_verification_applications",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_verify_apps_status_submitted",
        "coach_verification_applications",
        ["status", "submitted_at"],
    )
    op.create_index(
        "ix_verify_apps_coach_profile_id",
        "coach_verification_applications",
        ["coach_profile_id"],
    )

    op.create_table(
        "coach_verification_documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(length=64),
            sa.ForeignKey("coach_verification_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verify_docs_application_id",
        "coach_verification_documents",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_verify_docs_application_id", table_name="coach_verification_documents")
    op.drop_table("coach_verification_documents")
    op.drop_index("ix_verify_apps_coach_profile_id", table_name="coach_verification_applications")
    op.drop_index("ix_verify_apps_status_submitted", table_name="coach_verification_applications")
    op.drop_index("ix_verify_apps_user_status", table_name="coach_verification_applications")
    op.drop_table("coach_verification_applications")
    op.drop_column("coach_profiles", "verification_status")
    op.drop_column("coach_profiles", "verified_at")
    op.drop_column("coach_profiles", "is_verified")
