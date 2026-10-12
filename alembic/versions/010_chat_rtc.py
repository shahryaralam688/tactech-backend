"""Chat message media/call fields + human RTC sessions

Revision ID: 010_chat_rtc
Revises: 009_coach_conv_idx
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_chat_rtc"
down_revision: Union[str, None] = "009_coach_conv_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="text"),
    )
    op.add_column("chat_messages", sa.Column("duration_seconds", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("call_outcome", sa.String(length=120), nullable=True))

    op.create_table(
        "chat_rtc_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(length=64),
            sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_rtc_sessions_thread_id", "chat_rtc_sessions", ["thread_id"])
    op.create_index("ix_chat_rtc_sessions_created_by", "chat_rtc_sessions", ["created_by_user_id"])
    op.create_index("ix_chat_rtc_sessions_status", "chat_rtc_sessions", ["status"])


def downgrade() -> None:
    op.drop_table("chat_rtc_sessions")
    op.drop_column("chat_messages", "call_outcome")
    op.drop_column("chat_messages", "duration_seconds")
    op.drop_column("chat_messages", "kind")
