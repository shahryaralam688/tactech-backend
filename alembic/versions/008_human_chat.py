"""Trainer-trainee human chat + device push tokens

Revision ID: 008_human_chat
Revises: 007_pgvector_memory
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_human_chat"
down_revision: Union[str, None] = "007_pgvector_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trainer_user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trainee_user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=280), nullable=True),
        sa.Column("trainer_unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trainee_unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trainer_user_id", "trainee_user_id", name="uq_chat_threads_pair"),
    )
    op.create_index("ix_chat_threads_trainer_user_id", "chat_threads", ["trainer_user_id"])
    op.create_index("ix_chat_threads_trainee_user_id", "chat_threads", ["trainee_user_id"])
    op.create_index("ix_chat_threads_last_message_at", "chat_threads", ["last_message_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("thread_id", sa.String(length=64), sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachment_url", sa.String(length=512), nullable=True),
        sa.Column("attachment_type", sa.String(length=16), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("thread_id", "client_id", name="uq_chat_messages_client"),
    )
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])
    op.create_index("ix_chat_messages_sender_user_id", "chat_messages", ["sender_user_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    op.create_table(
        "device_push_tokens",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="ios"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "token", name="uq_device_push_tokens_user_token"),
    )
    op.create_index("ix_device_push_tokens_user_id", "device_push_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("device_push_tokens")
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
