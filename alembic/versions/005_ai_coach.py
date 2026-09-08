"""AI coach chat, memory vectors, WebRTC sessions

Revision ID: 005_ai_coach
Revises: 004_remaining_ios
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005_ai_coach"
down_revision: Union[str, None] = "004_remaining_ios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_conversations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="AI Coach"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coach_conversations_user_id", "coach_conversations", ["user_id"])

    op.create_table(
        "coach_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=64),
            sa.ForeignKey("coach_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("modality", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("audio_url", sa.String(length=512), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coach_messages_conversation_id", "coach_messages", ["conversation_id"])

    op.create_table(
        "coach_memory_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coach_memory_chunks_user_id", "coach_memory_chunks", ["user_id"])
    op.create_index("ix_coach_memory_chunks_source_type", "coach_memory_chunks", ["source_type"])

    op.create_table(
        "coach_rtc_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(length=64),
            sa.ForeignKey("coach_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_coach_rtc_sessions_user_id", "coach_rtc_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("coach_rtc_sessions")
    op.drop_table("coach_memory_chunks")
    op.drop_table("coach_messages")
    op.drop_table("coach_conversations")
