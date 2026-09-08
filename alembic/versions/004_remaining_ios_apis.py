"""profile, templates, preferences, support, soft-delete

Revision ID: 004_remaining_ios
Revises: 003_assessments
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004_remaining_ios"
down_revision: Union[str, None] = "003_assessments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("gender", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("height_cm", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("weight_kg", sa.Float(), nullable=True))
    op.add_column(
        "users",
        sa.Column("account_type", sa.String(length=32), nullable=False, server_default="Regular"),
    )
    op.add_column("users", sa.Column("avatar_url", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("avatar_asset", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("users", "account_type", server_default=None)

    op.add_column("workout_plans", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_workout_plans_deleted_at", "workout_plans", ["deleted_at"])

    op.create_table(
        "exercise_templates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("exercise_id", sa.String(length=64), nullable=False),
        sa.Column("trainer_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("tempo", sa.String(length=32), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("how_to", sa.Text(), nullable=True),
        sa.Column("side", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exercise_templates_exercise_id", "exercise_templates", ["exercise_id"])
    op.create_index("ix_exercise_templates_trainer_id", "exercise_templates", ["trainer_id"])

    op.create_table(
        "exercise_template_set_rows",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["exercise_templates.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_exercise_template_set_rows_template_id",
        "exercise_template_set_rows",
        ["template_id"],
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("notifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("security", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("language", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "app_feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("areas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_app_feedback_user_id", "app_feedback", ["user_id"])

    op.create_table(
        "support_conversations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_support_conversations_user_id", "support_conversations", ["user_id"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachment_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["support_conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_support_messages_conversation_id", "support_messages", ["conversation_id"])

    op.create_table(
        "trainer_assessments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainer_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainer_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_trainer_assessments_trainer_id", "trainer_assessments", ["trainer_id"])


def downgrade() -> None:
    op.drop_table("trainer_assessments")
    op.drop_table("support_messages")
    op.drop_table("support_conversations")
    op.drop_table("app_feedback")
    op.drop_table("user_preferences")
    op.drop_table("exercise_template_set_rows")
    op.drop_table("exercise_templates")
    op.drop_index("ix_workout_plans_deleted_at", table_name="workout_plans")
    op.drop_column("workout_plans", "deleted_at")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "bio")
    op.drop_column("users", "phone")
    op.drop_column("users", "avatar_asset")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "account_type")
    op.drop_column("users", "weight_kg")
    op.drop_column("users", "height_cm")
    op.drop_column("users", "location")
    op.drop_column("users", "gender")
